"""
Support Ticket System models (docs/tickets-module.md).

A Ticket is a client-reported problem or request tracked from intake to
closure. Four models:

TicketCategory  admin-managed classification ("Bug", "Billing", …). A table,
                not TextChoices — §4's own criterion: enums that admins change
                at runtime belong in a table; enums that change with releases
                belong in code.
SlaPolicy       the promised reaction speed per priority (one row each).
Ticket          the case itself: who reported it, what it is, where it stands.
TicketReply     one message on the ticket's conversation thread.

Tickets are NEVER deleted (no soft-delete flag either): a support history
with holes is worthless for audits and SLA reporting — finished tickets are
CLOSED, not removed.
"""

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex, OpClass
from django.contrib.postgres.search import SearchVector
from django.db import models
from django.db.models import Q
from django.db.models.functions import Upper

from apps.core.models import TimeStampedModel


class TicketCategory(TimeStampedModel):
    """
    What KIND of issue a ticket is. Categories are retired by flipping
    is_active — existing tickets keep pointing at a retired category (their
    history must not change), but new tickets can no longer choose it.
    """

    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "ticket categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class TicketPriority(models.TextChoices):
    """
    How urgent the ticket is — module-level (not nested in Ticket) because
    SlaPolicy shares the exact same choices; two copies would drift.
    """

    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    URGENT = "urgent", "Urgent"


class SlaPolicy(TimeStampedModel):
    """
    The Service Level Agreement per priority: how fast we promise to first
    respond and to resolve. One row per priority (DB-enforced). Seeded with
    defaults by a data migration; admins tune the numbers later.

    Minutes (not hours) so sub-hour promises like "urgent: 30 min first
    response" are representable without decimals.
    """

    priority = models.CharField(max_length=20, choices=TicketPriority.choices, unique=True)
    first_response_minutes = models.PositiveIntegerField()
    resolution_minutes = models.PositiveIntegerField()

    class Meta:
        verbose_name_plural = "SLA policies"
        constraints = [
            # A promise of "0 minutes" is a data-entry error, not a policy.
            models.CheckConstraint(
                condition=Q(first_response_minutes__gt=0) & Q(resolution_minutes__gt=0),
                name="sla_minutes_positive",
            ),
        ]

    def __str__(self):
        return f"SLA {self.priority}: respond {self.first_response_minutes}m"


class Ticket(TimeStampedModel):
    """
    One support case. Lifecycle is a controlled state machine — status moves
    only along ALLOWED_TRANSITIONS and only through services.py, because most
    moves carry side effects (timestamps, required fields, history rows).
    """

    class Status(models.TextChoices):
        OPEN = "open", "Open"  # logged, waiting for an agent
        IN_PROGRESS = "in_progress", "In progress"  # an agent is on it
        WAITING_ON_CLIENT = "waiting_on_client", "Waiting on client"  # blocked on customer
        RESOLVED = "resolved", "Resolved"  # fix delivered, awaiting confirmation
        CLOSED = "closed", "Closed"  # confirmed done / abandoned — terminal-ish

    # Which moves are legal FROM each status. Anything not listed here is a
    # 400 at the API. RESOLVED/CLOSED → IN_PROGRESS exists only via reopen().
    ALLOWED_TRANSITIONS = {
        Status.OPEN: {Status.IN_PROGRESS, Status.RESOLVED, Status.CLOSED},
        Status.IN_PROGRESS: {Status.WAITING_ON_CLIENT, Status.RESOLVED, Status.OPEN},
        Status.WAITING_ON_CLIENT: {Status.IN_PROGRESS, Status.RESOLVED, Status.CLOSED},
        Status.RESOLVED: {Status.CLOSED, Status.IN_PROGRESS},
        Status.CLOSED: {Status.IN_PROGRESS},
    }

    # The statuses where work is still owed — SLA breach checks and the
    # auto-escalation sweep only look at these.
    OPEN_STATUSES = (Status.OPEN, Status.IN_PROGRESS, Status.WAITING_ON_CLIENT)

    # -- who & what ----------------------------------------------------------
    # PROTECT: a client with support history can't be hard-deleted from under
    # its tickets (same rule as User→Client in §4).
    client = models.ForeignKey("clients.Client", on_delete=models.PROTECT, related_name="tickets")
    # The PERSON at the client who reported it. SET_NULL: the ticket record
    # outlives the contact; optional because phone-in reporters are sometimes
    # unknown at intake.
    contact = models.ForeignKey(
        "clients.Contact",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets",
    )
    subject = models.CharField(max_length=200)
    description = models.TextField()
    # PROTECT + is_active retirement (see TicketCategory docstring).
    category = models.ForeignKey(TicketCategory, on_delete=models.PROTECT, related_name="tickets")

    # -- workflow ------------------------------------------------------------
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    priority = models.CharField(
        max_length=20, choices=TicketPriority.choices, default=TicketPriority.MEDIUM
    )
    # SET_NULL: unassigned is a valid queue state (same as Task.assignee §4).
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tickets",
    )
    # The agent who logged the call/email — not the reporter (that's contact).
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_tickets",
    )

    # -- escalation ----------------------------------------------------------
    # A flag, not a status: an escalated ticket is still in_progress/open —
    # escalation changes who is WATCHING, not where the work IS.
    is_escalated = models.BooleanField(default=False)
    escalated_at = models.DateTimeField(null=True, blank=True)
    escalated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="escalated_tickets",
    )
    escalation_reason = models.CharField(max_length=255, blank=True)

    # -- SLA (denormalized ON PURPOSE) ---------------------------------------
    # Deadlines are stamped at creation from the SlaPolicy of the ticket's
    # priority. Copied, not looked up live, because (a) the promise made when
    # the ticket arrived must not silently change when an admin edits the
    # policy later, and (b) "overdue" filters need an indexed column to
    # compare against now(). Nullable: no policy row → no promise to track.
    first_response_due_at = models.DateTimeField(null=True, blank=True)
    resolution_due_at = models.DateTimeField(null=True, blank=True)
    # When the first customer-visible reply went out (internal notes don't
    # count — the client never saw those).
    first_response_at = models.DateTimeField(null=True, blank=True)

    # -- resolution ----------------------------------------------------------
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    resolution_summary = models.TextField(blank=True)
    # How often the "fix" bounced — a quality metric worth reporting on.
    reopened_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            # The queue screen's hot filters (§4: index the list-screen filters).
            models.Index(fields=["status", "priority"]),
            models.Index(fields=["assignee", "status"]),
            # The overdue sweep: WHERE status IN (open…) AND due < now().
            models.Index(fields=["resolution_due_at"]),
            # Global search: substring on Upper(subject) + stemmed word match
            # over subject+description (both expressions must match
            # services.py exactly, or the planner ignores the index).
            GinIndex(OpClass(Upper("subject"), name="gin_trgm_ops"), name="ticket_subject_trgm"),
            GinIndex(SearchVector("subject", "description", config="english"), name="ticket_fts"),
        ]
        constraints = [
            # The state machine's bookkeeping invariant, guarded by the DB
            # itself: resolved/closed tickets carry their timestamp, live ones
            # don't. Application bugs can't write a lying row.
            models.CheckConstraint(
                condition=(
                    Q(status__in=["resolved", "closed"], resolved_at__isnull=False)
                    | Q(status__in=["open", "in_progress", "waiting_on_client"], resolved_at=None)
                ),
                name="ticket_resolved_at_matches_status",
            ),
        ]

    # -- live SLA state (computed, not stored — "overdue" changes as the
    # clock ticks; a stored flag would be stale the second it was written) ---
    @property
    def is_first_response_overdue(self) -> bool:
        """We still owe the client a first reply and the deadline has passed."""
        from django.utils import timezone

        return (
            self.status in self.OPEN_STATUSES
            and self.first_response_at is None
            and self.first_response_due_at is not None
            and timezone.now() > self.first_response_due_at
        )

    @property
    def is_resolution_overdue(self) -> bool:
        """The ticket is still unfinished past its promised resolution time."""
        from django.utils import timezone

        return (
            self.status in self.OPEN_STATUSES
            and self.resolution_due_at is not None
            and timezone.now() > self.resolution_due_at
        )

    def __str__(self):
        return f"#{self.pk} {self.subject}"


class TicketReply(TimeStampedModel):
    """
    One message on a ticket's thread. APPEND-ONLY over the API (no edit, no
    delete): replies are the record of what was told to whom — SLA first-
    response times and dispute audits are computed from them, so they must be
    as immutable as Activity rows.

    is_internal=True marks team-only notes ("client is furious, handle with
    care") that a future client portal must never render. The flag exists NOW
    because retrofitting it later would mean guessing which historical replies
    were meant to be private.
    """

    # CASCADE: replies are meaningless without their ticket (only reachable
    # if a ticket were ever hard-deleted — the API never does).
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="replies")
    # SET_NULL: the thread outlives an agent's account (same as Note.author).
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="ticket_replies",
    )
    body = models.TextField()
    is_internal = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = "ticket replies"
        ordering = ["created_at"]  # a conversation reads oldest-first

    def __str__(self):
        return f"Reply #{self.pk} on ticket #{self.ticket_id}"
