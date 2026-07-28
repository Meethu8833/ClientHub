"""
Side-effectful ticket logic (§11: views stay thin). Every status move, the
SLA stamping, escalation and replies live here — each function is one atomic
unit of "change + its bookkeeping timestamps + its history row".

Why a state machine in services and not `PATCH {"status": ...}`:
almost every transition has side effects (resolve stamps resolved_at and
requires a summary; reopen clears it and bumps a counter; close stamps
closed_at). A writable status field would let callers skip the side effects
and corrupt the SLA metrics — so status is read-only in serializers and only
these functions move it.
"""

from django.db import transaction
from django.utils import timezone

# DRF's ValidationError (not Django's): raising it anywhere under a DRF view
# automatically becomes a 400 with our standard error shape. Django's own
# ValidationError would bubble up as a 500.
from rest_framework.exceptions import ValidationError

from apps.activities.models import Activity
from apps.activities.services import record
from apps.notifications.models import NotificationCategory
from apps.notifications.services import notify

from .models import SlaPolicy, Ticket, TicketReply


def _stamp_sla(ticket: Ticket) -> None:
    """
    Copy the current SlaPolicy for the ticket's priority onto the ticket as
    absolute deadlines (created_at + promised minutes). No policy row → no
    deadlines (nulls), which the API surfaces as "no SLA tracked".
    """
    policy = SlaPolicy.objects.filter(priority=ticket.priority).first()
    if policy is None:
        ticket.first_response_due_at = None
        ticket.resolution_due_at = None
        return
    base = ticket.created_at or timezone.now()
    ticket.first_response_due_at = base + timezone.timedelta(minutes=policy.first_response_minutes)
    ticket.resolution_due_at = base + timezone.timedelta(minutes=policy.resolution_minutes)


def _check_transition(ticket: Ticket, new_status: str) -> None:
    allowed = Ticket.ALLOWED_TRANSITIONS[ticket.status]
    if new_status not in allowed:
        raise ValidationError(
            {
                "status": f"Cannot move a {ticket.get_status_display().lower()} ticket "
                f"to {new_status}."
            }
        )


@transaction.atomic
def create_ticket(*, ticket: Ticket, actor) -> Ticket:
    """Persist a new ticket, stamp its SLA deadlines, open its timeline."""
    ticket.created_by = actor
    ticket.save()  # first save so auto_now_add fills created_at…
    _stamp_sla(ticket)  # …which the deadlines are computed from
    ticket.save(update_fields=["first_response_due_at", "resolution_due_at"])
    record(actor=actor, target=ticket, verb=Activity.Verb.CREATED, changes={})
    return ticket


@transaction.atomic
def update_ticket(*, ticket: Ticket, actor) -> Ticket:
    """
    Persist field edits (subject, description, category, contact, priority).
    A PRIORITY change re-stamps the SLA deadlines from the new policy — the
    promise follows the urgency — and gets its own timeline event because
    bumping priority is exactly the kind of change disputes are made of.
    """
    old = Ticket.objects.get(pk=ticket.pk)
    ticket.save()
    if ticket.priority != old.priority:
        _stamp_sla(ticket)
        ticket.save(update_fields=["first_response_due_at", "resolution_due_at"])
        record(
            actor=actor,
            target=ticket,
            verb=Activity.Verb.UPDATED,
            changes={"field": "priority", "from": old.priority, "to": ticket.priority},
        )
    return ticket


@transaction.atomic
def change_status(*, ticket: Ticket, new_status: str, actor) -> Ticket:
    """
    The one gate every move goes through: validates the transition, then
    writes the status + one status_changed history row. Callers below set
    their bookkeeping fields on the instance FIRST and let this full save()
    persist everything in one statement — the DB constraint ties resolved_at
    to status, so writing them in two steps would be rejected mid-flight.
    """
    _check_transition(ticket, new_status)
    old_status = ticket.status
    ticket.status = new_status
    ticket.save()
    record(
        actor=actor,
        target=ticket,
        verb=Activity.Verb.STATUS_CHANGED,
        changes={"field": "status", "from": old_status, "to": new_status},
    )
    return ticket


@transaction.atomic
def assign_ticket(*, ticket: Ticket, assignee, actor) -> Ticket:
    """
    Hand the ticket to an agent (or take it yourself — "claim"). Assigning an
    OPEN ticket auto-starts it: a ticket with an owner is being worked on.
    """
    if ticket.status in (Ticket.Status.RESOLVED, Ticket.Status.CLOSED):
        raise ValidationError({"detail": "Cannot assign a finished ticket — reopen it first."})
    old = ticket.assignee
    ticket.assignee = assignee
    ticket.save(update_fields=["assignee", "updated_at"])
    record(
        actor=actor,
        target=ticket,
        verb=Activity.Verb.ASSIGNED,
        changes={
            "from": {"id": old.pk, "name": _user_label(old)} if old else None,
            "to": {"id": assignee.pk, "name": _user_label(assignee)} if assignee else None,
        },
    )
    if assignee is not None:
        notify(
            recipients=[assignee],
            category=NotificationCategory.TICKET,
            title=f"You were assigned ticket #{ticket.pk}: {ticket.subject}",
            body=f"{_user_label(actor)} assigned you this ticket.",
            actor=actor,
            target=ticket,
        )
    # An owner means work has started; losing the owner sends it back to the
    # queue — the status should always tell the truth about the assignee.
    if ticket.status == Ticket.Status.OPEN and assignee is not None:
        change_status(ticket=ticket, new_status=Ticket.Status.IN_PROGRESS, actor=actor)
    elif ticket.status == Ticket.Status.IN_PROGRESS and assignee is None:
        change_status(ticket=ticket, new_status=Ticket.Status.OPEN, actor=actor)
    return ticket


@transaction.atomic
def escalate_ticket(*, ticket: Ticket, actor, reason: str = "") -> Ticket:
    """
    Raise the flag that pulls a manager's eyes onto the ticket. actor=None is
    the system (the overdue sweep). Idempotent-hostile on purpose: escalating
    twice is a caller bug, not a no-op.
    """
    if ticket.status not in Ticket.OPEN_STATUSES:
        raise ValidationError({"detail": "Only an unfinished ticket can be escalated."})
    if ticket.is_escalated:
        raise ValidationError({"detail": "This ticket is already escalated."})
    ticket.is_escalated = True
    ticket.escalated_at = timezone.now()
    ticket.escalated_by = actor
    ticket.escalation_reason = reason
    ticket.save(
        update_fields=[
            "is_escalated",
            "escalated_at",
            "escalated_by",
            "escalation_reason",
            "updated_at",
        ]
    )
    record(
        actor=actor,
        target=ticket,
        verb=Activity.Verb.ESCALATED,
        changes={"reason": reason},
    )
    return ticket


@transaction.atomic
def resolve_ticket(*, ticket: Ticket, actor, summary: str) -> Ticket:
    """
    Deliver the outcome. The summary is REQUIRED (serializer-enforced): a
    resolved ticket that doesn't say what was done teaches the next agent
    nothing when the same client calls again.
    """
    ticket.resolved_at = timezone.now()
    ticket.resolution_summary = summary
    return change_status(ticket=ticket, new_status=Ticket.Status.RESOLVED, actor=actor)


@transaction.atomic
def close_ticket(*, ticket: Ticket, actor) -> Ticket:
    """
    Final confirmation (or abandonment of an open ticket, e.g. spam). Closing
    something that was never resolved still stamps resolved_at — the DB
    constraint says a closed ticket carries its end timestamp.
    """
    if ticket.resolved_at is None:
        ticket.resolved_at = timezone.now()
    ticket.closed_at = timezone.now()
    return change_status(ticket=ticket, new_status=Ticket.Status.CLOSED, actor=actor)


@transaction.atomic
def reopen_ticket(*, ticket: Ticket, actor) -> Ticket:
    """
    The client says the fix didn't stick. Clears the resolution bookkeeping
    (the constraint demands it for a live ticket) but keeps the summary text
    visible in history via the timeline; bumps the bounce counter.
    """
    if ticket.status not in (Ticket.Status.RESOLVED, Ticket.Status.CLOSED):
        raise ValidationError({"detail": "Only a resolved or closed ticket can be reopened."})
    ticket.resolved_at = None
    ticket.closed_at = None
    ticket.reopened_count += 1
    return change_status(ticket=ticket, new_status=Ticket.Status.IN_PROGRESS, actor=actor)


@transaction.atomic
def add_reply(*, ticket: Ticket, author, body: str, is_internal: bool) -> TicketReply:
    """
    Append a message to the thread. The FIRST customer-visible reply stops
    the first-response SLA clock; internal notes never do (the client hasn't
    heard from us yet). Also un-blocks a waiting ticket when a public answer
    goes out is left to agents — replying does not move status automatically,
    because "we sent a message" and "we are working again" are different facts.
    """
    if ticket.status == Ticket.Status.CLOSED:
        raise ValidationError({"detail": "This ticket is closed — reopen it to continue."})
    reply = TicketReply.objects.create(
        ticket=ticket, author=author, body=body, is_internal=is_internal
    )
    if not is_internal and ticket.first_response_at is None:
        ticket.first_response_at = reply.created_at
        ticket.save(update_fields=["first_response_at", "updated_at"])
    return reply


def _user_label(user) -> str:
    return user.get_full_name() or user.email
