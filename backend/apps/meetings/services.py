"""
Side-effectful meeting logic (§11: views stay thin). Scheduling, conflict
detection, every status move, RSVP, reminder stamping, minutes and the ICS
export live here — each function is one atomic unit of "change + its
bookkeeping + its history row (+ its email)".

Why a state machine and not `PATCH {"status": ...}`: every transition has
side effects (cancel stamps who/when/why and emails the room; complete
stamps completed_at and unlocks minutes). A writable status field would let
callers skip them, so status is read-only in serializers and only these
functions move it.

Emails are best-effort: a down SMTP server must never turn a valid
scheduling request into a 500 — failures are logged, the transaction
proceeds. (Reminder emails are different: the cron command retries them
because unsent rows keep sent_at=NULL.)
"""

import logging
from datetime import timezone as dt_timezone

from django.core.mail import EmailMessage
from django.db import transaction
from django.utils import timezone

# DRF's ValidationError (not Django's): raising it anywhere under a DRF view
# automatically becomes a 400 with our standard error shape.
from rest_framework.exceptions import ValidationError

from apps.activities.models import Activity
from apps.activities.services import record

from .models import ActionItem, Meeting, MeetingAttendee, MeetingMinutes, MeetingReminder

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Conflict detection
# --------------------------------------------------------------------------


def find_conflicts(*, user_ids, start, end, exclude_meeting_id=None):
    """
    Meetings that would double-book any of `user_ids` in [start, end).

    Two intervals overlap iff A starts before B ends AND A ends after B
    starts — the classic test; no special cases needed. Only SCHEDULED
    meetings block a slot, and only for people whose presence is REQUIRED
    (organizers always are; optional invitees may be double-booked).
    """
    from django.db.models import Q

    qs = Meeting.objects.filter(
        status=Meeting.Status.SCHEDULED,
        scheduled_start__lt=end,
        scheduled_end__gt=start,
    ).filter(
        Q(organizer_id__in=user_ids)
        | Q(attendees__user_id__in=user_ids, attendees__is_required=True)
    )
    if exclude_meeting_id:
        qs = qs.exclude(pk=exclude_meeting_id)
    return qs.distinct()


def _reject_conflicts(*, user_ids, start, end, exclude_meeting_id=None):
    conflicts = find_conflicts(
        user_ids=user_ids, start=start, end=end, exclude_meeting_id=exclude_meeting_id
    )
    if conflicts.exists():
        raise ValidationError(
            {
                "scheduled_start": [
                    "Time conflict with: "
                    + "; ".join(
                        f"#{m.pk} {m.title} ({m.scheduled_start:%Y-%m-%d %H:%M})"
                        for m in conflicts[:5]
                    )
                ]
            }
        )


# --------------------------------------------------------------------------
# Reminders (stamping — sending lives in the management command)
# --------------------------------------------------------------------------


def _stamp_reminders(meeting: Meeting, offsets) -> None:
    """
    (Re)compute absolute remind_at times from the meeting start. Already-sent
    reminders are left untouched — they are history; only pending nudges move
    with the meeting.
    """
    meeting.reminders.filter(sent_at__isnull=True).delete()
    existing = set(meeting.reminders.values_list("offset_minutes", flat=True))
    MeetingReminder.objects.bulk_create(
        MeetingReminder(
            meeting=meeting,
            offset_minutes=offset,
            remind_at=meeting.scheduled_start - timezone.timedelta(minutes=offset),
        )
        for offset in offsets
        if offset not in existing  # a sent reminder at this offset stays sent
    )


# --------------------------------------------------------------------------
# Email helpers
# --------------------------------------------------------------------------


def attendee_emails(meeting: Meeting):
    """Every reachable participant: internal users + client contacts."""
    emails = []
    for attendee in meeting.attendees.select_related("user", "contact"):
        email = attendee.user.email if attendee.user_id else attendee.contact.email
        if email:
            emails.append(email)
    return emails


def notify_attendees(meeting: Meeting, subject: str, body: str) -> None:
    recipients = attendee_emails(meeting)
    if not recipients:
        return
    try:
        EmailMessage(subject=subject, body=body, to=recipients).send()
    except Exception:  # noqa: BLE001 — email is best-effort, never a 500
        logger.exception("Failed to send meeting email for meeting #%s", meeting.pk)


def _when_line(meeting: Meeting) -> str:
    return (
        f"{meeting.scheduled_start:%A %d %b %Y, %H:%M} – {meeting.scheduled_end:%H:%M} UTC"
        f" ({meeting.get_mode_display()}"
        + (f", {meeting.location}" if meeting.location else "")
        + (f", {meeting.meeting_link}" if meeting.meeting_link else "")
        + ")"
    )


# --------------------------------------------------------------------------
# Lifecycle
# --------------------------------------------------------------------------


def _check_transition(meeting: Meeting, new_status: str) -> None:
    allowed = Meeting.ALLOWED_TRANSITIONS[meeting.status]
    if new_status not in allowed:
        raise ValidationError(
            {
                "status": f"Cannot move a {meeting.get_status_display().lower()} meeting "
                f"to {new_status}."
            }
        )


def _change_status(*, meeting: Meeting, new_status: str, actor) -> Meeting:
    """
    The one gate every move goes through. Callers set their bookkeeping
    fields on the instance FIRST; this full save() persists everything in
    one statement — the DB constraints tie the timestamps to the status, so
    writing them in two steps would be rejected mid-flight.
    """
    _check_transition(meeting, new_status)
    old_status = meeting.status
    meeting.status = new_status
    meeting.save()
    record(
        actor=actor,
        target=meeting,
        verb=Activity.Verb.STATUS_CHANGED,
        changes={"field": "status", "from": old_status, "to": new_status},
    )
    return meeting


@transaction.atomic
def create_meeting(
    *, meeting: Meeting, actor, user_attendees=(), contact_attendees=(), reminder_offsets=()
) -> Meeting:
    """
    Persist a new meeting with its people and its nudges, then invite the
    room. The organizer is always an (auto-accepted) attendee — they are
    obviously coming to their own meeting, and having their row makes the
    attendee list complete and conflict detection uniform.
    """
    meeting.organizer = actor
    required_users = {actor.pk} | {u.pk for u in user_attendees}
    _reject_conflicts(
        user_ids=required_users, start=meeting.scheduled_start, end=meeting.scheduled_end
    )
    meeting.save()

    MeetingAttendee.objects.create(
        meeting=meeting,
        user=actor,
        response=MeetingAttendee.Response.ACCEPTED,
        responded_at=timezone.now(),
    )
    MeetingAttendee.objects.bulk_create(
        MeetingAttendee(meeting=meeting, user=user) for user in user_attendees if user != actor
    )
    MeetingAttendee.objects.bulk_create(
        MeetingAttendee(meeting=meeting, contact=contact) for contact in contact_attendees
    )
    _stamp_reminders(meeting, reminder_offsets)

    record(actor=actor, target=meeting, verb=Activity.Verb.CREATED, changes={})
    notify_attendees(
        meeting,
        subject=f"Meeting invitation: {meeting.title}",
        body=(
            f"You are invited to '{meeting.title}'.\n\n"
            f"When: {_when_line(meeting)}\n"
            f"Organizer: {_user_label(actor)}\n\n"
            f"Agenda:\n{meeting.agenda or '(none)'}"
        ),
    )
    return meeting


@transaction.atomic
def update_meeting(*, meeting: Meeting, actor) -> Meeting:
    """Persist scalar edits (title, agenda, mode, location, link, client…)."""
    meeting.save()
    record(actor=actor, target=meeting, verb=Activity.Verb.UPDATED, changes={})
    return meeting


@transaction.atomic
def reschedule_meeting(*, meeting: Meeting, actor, start, end) -> Meeting:
    """
    Move the meeting. Three side effects a raw PATCH would skip:
    reminders re-stamp to the new start, every RSVP except the organizer's
    resets to PENDING (an acceptance of Tuesday says nothing about Friday),
    and the room is notified.
    """
    if meeting.status != Meeting.Status.SCHEDULED:
        raise ValidationError({"detail": "Only a scheduled meeting can be rescheduled."})

    required_users = set(
        meeting.attendees.filter(user__isnull=False, is_required=True).values_list(
            "user_id", flat=True
        )
    ) | {meeting.organizer_id}
    _reject_conflicts(user_ids=required_users, start=start, end=end, exclude_meeting_id=meeting.pk)

    old_start = meeting.scheduled_start
    meeting.scheduled_start = start
    meeting.scheduled_end = end
    meeting.rescheduled_count += 1
    meeting.save()

    # list() BEFORE _stamp_reminders runs: querysets are lazy, and the first
    # thing _stamp_reminders does is DELETE these rows — an unevaluated
    # queryset would come back empty.
    pending_offsets = list(
        meeting.reminders.filter(sent_at__isnull=True).values_list("offset_minutes", flat=True)
    )
    _stamp_reminders(meeting, pending_offsets)
    meeting.attendees.exclude(user_id=meeting.organizer_id).update(
        response=MeetingAttendee.Response.PENDING, responded_at=None
    )

    record(
        actor=actor,
        target=meeting,
        verb=Activity.Verb.RESCHEDULED,
        changes={"from": old_start.isoformat(), "to": start.isoformat()},
    )
    notify_attendees(
        meeting,
        subject=f"Rescheduled: {meeting.title}",
        body=f"'{meeting.title}' has moved.\n\nNew time: {_when_line(meeting)}",
    )
    return meeting


@transaction.atomic
def cancel_meeting(*, meeting: Meeting, actor, reason: str) -> Meeting:
    """Call it off — keeps the record, the reason, and tells the room."""
    meeting.cancelled_at = timezone.now()
    meeting.cancelled_by = actor
    meeting.cancel_reason = reason
    meeting = _change_status(meeting=meeting, new_status=Meeting.Status.CANCELLED, actor=actor)
    notify_attendees(
        meeting,
        subject=f"Cancelled: {meeting.title}",
        body=f"'{meeting.title}' ({_when_line(meeting)}) is cancelled.\nReason: {reason}",
    )
    return meeting


@transaction.atomic
def complete_meeting(*, meeting: Meeting, actor) -> Meeting:
    """The meeting happened. Completing unlocks minutes and action items."""
    if timezone.now() < meeting.scheduled_start:
        raise ValidationError({"detail": "This meeting has not started yet."})
    meeting.completed_at = timezone.now()
    return _change_status(meeting=meeting, new_status=Meeting.Status.COMPLETED, actor=actor)


@transaction.atomic
def mark_no_show(*, meeting: Meeting, actor) -> Meeting:
    """We were there, they weren't — a relationship signal worth recording."""
    if timezone.now() < meeting.scheduled_start:
        raise ValidationError({"detail": "This meeting has not started yet."})
    return _change_status(meeting=meeting, new_status=Meeting.Status.NO_SHOW, actor=actor)


# --------------------------------------------------------------------------
# Attendees & RSVP
# --------------------------------------------------------------------------


@transaction.atomic
def add_attendee(*, meeting: Meeting, actor, user=None, contact=None, is_required=True):
    """Invite one more person (only to a still-scheduled meeting)."""
    if meeting.status != Meeting.Status.SCHEDULED:
        raise ValidationError({"detail": "Attendees can only change on a scheduled meeting."})
    if user is not None:
        if meeting.attendees.filter(user=user).exists():
            raise ValidationError({"user_id": "Already an attendee."})
        if is_required:
            _reject_conflicts(
                user_ids={user.pk},
                start=meeting.scheduled_start,
                end=meeting.scheduled_end,
                exclude_meeting_id=meeting.pk,
            )
    else:
        if meeting.client_id is None or contact.client_id != meeting.client_id:
            raise ValidationError({"contact_id": "This contact does not belong to the client."})
        if meeting.attendees.filter(contact=contact).exists():
            raise ValidationError({"contact_id": "Already an attendee."})

    attendee = MeetingAttendee.objects.create(
        meeting=meeting, user=user, contact=contact, is_required=is_required
    )
    record(
        actor=actor,
        target=meeting,
        verb=Activity.Verb.ATTENDEE_ADDED,
        changes={"attendee": _person_label(attendee)},
    )
    return attendee


@transaction.atomic
def remove_attendee(*, attendee: MeetingAttendee, actor) -> None:
    meeting = attendee.meeting
    if meeting.status != Meeting.Status.SCHEDULED:
        raise ValidationError({"detail": "Attendees can only change on a scheduled meeting."})
    if attendee.user_id == meeting.organizer_id:
        raise ValidationError({"detail": "The organizer cannot be removed from their meeting."})
    label = _person_label(attendee)
    attendee.delete()
    record(
        actor=actor,
        target=meeting,
        verb=Activity.Verb.ATTENDEE_REMOVED,
        changes={"attendee": label},
    )


@transaction.atomic
def respond(*, meeting: Meeting, user, response: str) -> MeetingAttendee:
    """RSVP by the logged-in user — organizer consent is not required."""
    if meeting.status != Meeting.Status.SCHEDULED:
        raise ValidationError({"detail": "This meeting is no longer open for responses."})
    attendee = meeting.attendees.filter(user=user).first()
    if attendee is None:
        raise ValidationError({"detail": "You are not an attendee of this meeting."})
    attendee.response = response
    attendee.responded_at = timezone.now()
    attendee.save(update_fields=["response", "responded_at", "updated_at"])
    return attendee


# --------------------------------------------------------------------------
# Minutes & action items
# --------------------------------------------------------------------------


@transaction.atomic
def save_minutes(*, meeting: Meeting, actor, content: str) -> MeetingMinutes:
    """
    Create-or-update the MoM (PUT semantics: the caller sends the full text).
    Only for COMPLETED meetings — you cannot minute what hasn't happened, and
    a cancelled meeting has nothing to minute.
    """
    if meeting.status != Meeting.Status.COMPLETED:
        raise ValidationError({"detail": "Minutes can only be recorded on a completed meeting."})
    minutes, created = MeetingMinutes.objects.update_or_create(
        meeting=meeting, defaults={"content": content, "recorded_by": actor}
    )
    if created:
        record(actor=actor, target=meeting, verb=Activity.Verb.MINUTES_RECORDED, changes={})
    return minutes


@transaction.atomic
def add_action_item(*, meeting: Meeting, description, owner=None, due_date=None) -> ActionItem:
    if meeting.status != Meeting.Status.COMPLETED:
        raise ValidationError({"detail": "Action items come out of a completed meeting."})
    return ActionItem.objects.create(
        meeting=meeting, description=description, owner=owner, due_date=due_date
    )


# --------------------------------------------------------------------------
# Calendar integration — ICS export (RFC 5545)
# --------------------------------------------------------------------------


def _ics_escape(text: str) -> str:
    """RFC 5545: backslash-escape structural characters, encode newlines."""
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ics_datetime(dt) -> str:
    """UTC basic format: 20260727T143000Z."""
    return dt.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_ics(meeting: Meeting) -> str:
    """
    One VEVENT the user can import into Google Calendar / Outlook / Apple
    Calendar. The UID is stable per meeting, and SEQUENCE increments with
    every reschedule — that is how calendar clients know an imported file
    UPDATES the existing event instead of duplicating it.
    """
    status = {
        Meeting.Status.SCHEDULED: "CONFIRMED",
        Meeting.Status.COMPLETED: "CONFIRMED",
        Meeting.Status.CANCELLED: "CANCELLED",
        Meeting.Status.NO_SHOW: "CONFIRMED",
    }[meeting.status]
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ClientHub//Meetings//EN",
        "BEGIN:VEVENT",
        f"UID:meeting-{meeting.pk}@clienthub",
        f"SEQUENCE:{meeting.rescheduled_count}",
        f"DTSTAMP:{_ics_datetime(timezone.now())}",
        f"DTSTART:{_ics_datetime(meeting.scheduled_start)}",
        f"DTEND:{_ics_datetime(meeting.scheduled_end)}",
        f"SUMMARY:{_ics_escape(meeting.title)}",
        f"STATUS:{status}",
    ]
    if meeting.agenda:
        lines.append(f"DESCRIPTION:{_ics_escape(meeting.agenda)}")
    location = meeting.meeting_link or meeting.location
    if location:
        lines.append(f"LOCATION:{_ics_escape(location)}")
    lines.append(
        f"ORGANIZER;CN={_ics_escape(_user_label(meeting.organizer))}:"
        f"mailto:{meeting.organizer.email}"
    )
    for email in attendee_emails(meeting):
        lines.append(f"ATTENDEE:mailto:{email}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    # RFC 5545 mandates CRLF line endings.
    return "\r\n".join(lines) + "\r\n"


def _user_label(user) -> str:
    return user.get_full_name() or user.email


def _person_label(attendee: MeetingAttendee) -> dict:
    if attendee.user_id:
        return {"kind": "user", "id": attendee.user_id, "name": _user_label(attendee.user)}
    return {"kind": "contact", "id": attendee.contact_id, "name": attendee.contact.name}
