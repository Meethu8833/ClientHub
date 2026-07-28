"""
Meeting Scheduler models (docs/meetings-module.md).

A Meeting is a scheduled conversation — with a client, about a project, or
purely internal. Five models:

Meeting          the event: when, where/how, about whom, organized by whom.
MeetingAttendee  one participant — EITHER an internal user OR a client
                 contact (XOR, DB-enforced) — with their RSVP state.
MeetingReminder  one "nudge N minutes before start", sent by a cron command.
MeetingMinutes   the ONE written record of what was discussed (OneToOne).
ActionItem       one follow-up task agreed in the meeting.

Meetings are never hard-deleted: a CRM's meeting history is evidence of the
relationship ("we met them six times before they signed"). A meeting that
won't happen is CANCELLED, which keeps the record and the reason.
"""

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.core.models import TimeStampedModel


class Meeting(TimeStampedModel):
    """
    One scheduled event. Lifecycle is a small state machine: SCHEDULED is the
    only live state; the three terminal states record HOW it ended. Status
    moves only through services.py — every move stamps timestamps and writes
    a timeline row, so a writable status field would corrupt the record.
    Rescheduling is NOT a status (the meeting is still scheduled) — it bumps
    `rescheduled_count` and rewrites the times.
    """

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"  # upcoming (or happening now)
        COMPLETED = "completed", "Completed"  # took place
        CANCELLED = "cancelled", "Cancelled"  # called off beforehand, with reason
        NO_SHOW = "no_show", "No show"  # we showed up, the other side didn't

    # Everything not listed is a 400 at the API. All three ends are terminal:
    # "reviving" a finished meeting is scheduling a NEW one (fresh invites,
    # fresh reminders) — editing history would lie about what happened.
    ALLOWED_TRANSITIONS = {
        Status.SCHEDULED: {Status.COMPLETED, Status.CANCELLED, Status.NO_SHOW},
        Status.COMPLETED: set(),
        Status.CANCELLED: set(),
        Status.NO_SHOW: set(),
    }

    class Mode(models.TextChoices):
        ONLINE = "online", "Online"  # link matters
        IN_PERSON = "in_person", "In person"  # location matters
        PHONE = "phone", "Phone"  # neither — a number in `location`

    # -- what & about whom ---------------------------------------------------
    title = models.CharField(max_length=200)
    # The plan for the meeting (free text). Named agenda, not description:
    # what we INTEND to discuss — the minutes record what actually was.
    agenda = models.TextField(blank=True)
    # Optional: internal meetings have no client. PROTECT — a client with
    # meeting history can't be hard-deleted from under it (same §4 rule as
    # tickets/projects).
    client = models.ForeignKey(
        "clients.Client",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="meetings",
    )
    # Optional narrowing: "about project X". SET_NULL — the meeting record
    # outlives a hard-deleted project; the client link still says who it
    # was with.
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meetings",
    )

    # -- when & where --------------------------------------------------------
    scheduled_start = models.DateTimeField()
    scheduled_end = models.DateTimeField()
    mode = models.CharField(max_length=20, choices=Mode.choices, default=Mode.ONLINE)
    # Room name, address, or phone number depending on mode.
    location = models.CharField(max_length=255, blank=True)
    meeting_link = models.URLField(blank=True)

    # -- who runs it ---------------------------------------------------------
    # PROTECT: the organizer is this record's owner (permission anchor) and
    # users are soft-deleted anyway — losing the organizer would orphan the
    # ownership rule.
    organizer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="organized_meetings",
    )

    # -- lifecycle bookkeeping ----------------------------------------------
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cancelled_meetings",
    )
    cancel_reason = models.CharField(max_length=255, blank=True)
    # How often the time moved — chronic rescheduling is a relationship
    # health signal worth reporting on (like Ticket.reopened_count).
    rescheduled_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-scheduled_start"]
        indexes = [
            # The two hot screens: "upcoming/past meetings" (calendar range
            # scans filter status + start) and "my organized meetings".
            models.Index(fields=["status", "scheduled_start"]),
            models.Index(fields=["organizer", "scheduled_start"]),
        ]
        constraints = [
            # A meeting that ends before it starts is a data bug, rejected by
            # the DB itself — the serializer's 400 is just the friendly copy.
            models.CheckConstraint(
                condition=Q(scheduled_end__gt=F("scheduled_start")),
                name="meeting_end_after_start",
            ),
            # Terminal-state bookkeeping can't lie: cancelled ⇔ cancelled_at.
            models.CheckConstraint(
                condition=(
                    Q(status="cancelled", cancelled_at__isnull=False)
                    | (~Q(status="cancelled") & Q(cancelled_at=None))
                ),
                name="meeting_cancelled_at_matches_status",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="completed", completed_at__isnull=False)
                    | (~Q(status="completed") & Q(completed_at=None))
                ),
                name="meeting_completed_at_matches_status",
            ),
        ]

    @property
    def duration_minutes(self) -> int:
        return int((self.scheduled_end - self.scheduled_start).total_seconds() // 60)

    @property
    def is_upcoming(self) -> bool:
        """Still scheduled and not yet started — computed, never stored."""
        return self.status == self.Status.SCHEDULED and self.scheduled_start > timezone.now()

    def __str__(self):
        return f"{self.title} @ {self.scheduled_start:%Y-%m-%d %H:%M}"


class MeetingAttendee(TimeStampedModel):
    """
    One participant. Two KINDS of people attend CRM meetings — our own users
    (who log in and RSVP) and the client's contacts (who don't have logins).
    One table with two nullable FKs and a DB-enforced XOR beats two tables:
    the attendee list renders as one collection, and the constraint makes a
    row that is both/neither impossible no matter what application code does.
    """

    class Response(models.TextChoices):
        PENDING = "pending", "Pending"  # invited, hasn't answered
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"
        TENTATIVE = "tentative", "Tentative"  # "maybe" — real calendars need it

    # CASCADE both ways: an attendee row is meaningless without its meeting,
    # and without its person (people rows are soft-deleted, so in practice
    # these cascades never fire from the API).
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="attendees")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="meeting_attendances",
    )
    contact = models.ForeignKey(
        "clients.Contact",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="meeting_attendances",
    )
    # Required attendees block the slot (conflict detection); optional ones
    # are FYI invites and may be double-booked.
    is_required = models.BooleanField(default=True)
    response = models.CharField(max_length=20, choices=Response.choices, default=Response.PENDING)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            # Exactly ONE of user/contact — the XOR that makes one table safe.
            models.CheckConstraint(
                condition=(
                    Q(user__isnull=False, contact__isnull=True)
                    | Q(user__isnull=True, contact__isnull=False)
                ),
                name="attendee_user_xor_contact",
            ),
            # Nobody is invited twice. Conditional: NULLs never collide in
            # SQL, so a plain unique on (meeting, user) wouldn't guard rows
            # where user is NULL — the two partial uniques cover each kind.
            models.UniqueConstraint(
                fields=["meeting", "user"],
                condition=Q(user__isnull=False),
                name="uniq_meeting_user_attendee",
            ),
            models.UniqueConstraint(
                fields=["meeting", "contact"],
                condition=Q(contact__isnull=False),
                name="uniq_meeting_contact_attendee",
            ),
        ]

    @property
    def person(self):
        """The actual human behind the row, whichever kind it is."""
        return self.user or self.contact

    def __str__(self):
        return f"{self.person} @ meeting #{self.meeting_id}"


class MeetingReminder(TimeStampedModel):
    """
    One scheduled nudge, e.g. "email everyone 60 minutes before start".

    `remind_at` is DENORMALIZED on purpose (same reasoning as ticket SLA
    deadlines): the cron sweep needs an indexed absolute time to compare with
    now() — computing start-minus-offset per row per minute doesn't index.
    Rescheduling the meeting re-stamps remind_at on every unsent reminder.
    `sent_at` doubles as the idempotency guard: the sweep only picks up rows
    where it is NULL, so a reminder can never be sent twice.
    """

    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="reminders")
    offset_minutes = models.PositiveIntegerField()
    remind_at = models.DateTimeField()
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["remind_at"]
        indexes = [
            # The sweep: WHERE sent_at IS NULL AND remind_at <= now().
            models.Index(fields=["remind_at"]),
        ]
        constraints = [
            # Two reminders at the same offset are one reminder.
            models.UniqueConstraint(
                fields=["meeting", "offset_minutes"], name="uniq_meeting_reminder_offset"
            ),
            models.CheckConstraint(
                condition=Q(offset_minutes__gt=0), name="reminder_offset_positive"
            ),
        ]

    def __str__(self):
        return f"Remind {self.offset_minutes}m before meeting #{self.meeting_id}"


class MeetingMinutes(TimeStampedModel):
    """
    Minutes of Meeting (MoM): the single written record of what was discussed
    and decided. OneToOne — a meeting has AT MOST one MoM document (multiple
    would raise "which one is authoritative?"); the API create-or-updates it
    via PUT. Only COMPLETED meetings may have minutes: you cannot record what
    was said in a meeting that hasn't happened.
    """

    meeting = models.OneToOneField(Meeting, on_delete=models.CASCADE, related_name="minutes")
    content = models.TextField()
    # SET_NULL: the record outlives the recorder's account (§4 pattern).
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="recorded_minutes",
    )

    class Meta:
        verbose_name_plural = "meeting minutes"

    def __str__(self):
        return f"Minutes of meeting #{self.meeting_id}"


class ActionItem(TimeStampedModel):
    """
    One follow-up agreed in the meeting ("send revised quotation by Friday").
    FK to the Meeting (not to MeetingMinutes): follow-ups exist even when
    nobody wrote formal minutes. `owner` is the internal user on the hook —
    SET_NULL because the commitment outlives an account; unowned items are a
    valid "someone pick this up" state (same as Task.assignee §4).
    """

    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="action_items")
    description = models.CharField(max_length=255)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meeting_action_items",
    )
    due_date = models.DateField(null=True, blank=True)
    is_done = models.BooleanField(default=False)

    class Meta:
        ordering = ["is_done", "due_date", "pk"]  # open items first, most urgent on top

    def __str__(self):
        return self.description
