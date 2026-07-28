"""
Notification system models (docs/notifications-module.md).

One EVENT ("you were assigned ticket #42") can travel over three CHANNELS:

in-app   a `Notification` row the React bell icon polls — always cheap,
         always synchronous (it is just an INSERT in the caller's transaction).
email    never sent inline in the request: an `EmailOutbox` row is queued and
         a cron worker (send_queued_emails) delivers it with retries.
push     a message to the user's registered `PushDevice` tokens, dispatched
         after commit (an external side effect must never fire for a
         transaction that rolls back).

`NotificationPreference` is the per-user switchboard deciding which channels
each category may use. Producers everywhere call ONE function —
services.notify() — and never touch these tables directly.
"""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel


class NotificationCategory(models.TextChoices):
    """
    WHAT AREA an event belongs to — the unit users toggle in preferences.
    Coarse on purpose: users think "stop emailing me about meetings", not
    "mute event #17". A new module = one new member here (code change,
    like every other enum in this project — ARCHITECTURE.md §4).
    """

    TICKET = "ticket", "Tickets"
    MEETING = "meeting", "Meetings"
    PROJECT = "project", "Projects & tasks"
    BILLING = "billing", "Billing"
    SYSTEM = "system", "System"


class Notification(TimeStampedModel):
    """
    One in-app notification for ONE user. Fan-out happens at write time:
    an event with five recipients creates five rows, each carrying its own
    read state — the alternative (one event row + a read-tracking join
    table) only pays off at millions of users.
    """

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,  # a user's notifications die with the account
        related_name="notifications",
    )
    # Who caused the event ("Maria assigned you…"). SET_NULL: the
    # notification outlives the actor's account (§4 pattern).
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="triggered_notifications",
    )
    category = models.CharField(max_length=20, choices=NotificationCategory.choices)
    # The rendered sentence, stored denormalized: what the event MEANT is
    # frozen at send time even if the ticket is later renamed or deleted.
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True)

    # Optional link to the object the event is about (same GenericFK pattern
    # as Document/Note/Activity) — the frontend uses it to deep-link.
    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    object_id = models.PositiveBigIntegerField(null=True, blank=True)
    target = GenericForeignKey("content_type", "object_id")

    # NULL = unread. One nullable timestamp instead of a boolean + a
    # timestamp: two fields that could contradict each other collapse into
    # one that cannot, and "when was it read" comes for free.
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            # The two hot queries: the bell's badge (recipient + unread)
            # and the dropdown list (recipient, newest first).
            models.Index(fields=["recipient", "read_at"]),
            models.Index(fields=["recipient", "-created_at"]),
        ]

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    def __str__(self):
        return f"→ {self.recipient}: {self.title}"


class NotificationPreference(TimeStampedModel):
    """
    One user's channel switches for ONE category (row created lazily on
    first read/write; a missing row means "all defaults"). Per-category
    rows instead of one wide row of booleans: adding a category never
    needs a migration of this table.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )
    category = models.CharField(max_length=20, choices=NotificationCategory.choices)
    in_app_enabled = models.BooleanField(default=True)
    email_enabled = models.BooleanField(default=True)
    push_enabled = models.BooleanField(default=True)

    class Meta:
        constraints = [
            # One switchboard row per (user, category) — an upsert target.
            models.UniqueConstraint(fields=["user", "category"], name="uniq_user_category_pref"),
        ]

    def __str__(self):
        return f"{self.user} / {self.category}"


class PushDevice(TimeStampedModel):
    """
    One browser/phone the user allowed push on. The `token` is the address
    the push service (FCM / a Web-Push endpoint) gave that device — we
    store it, we never mint it. A user has many devices; a token belongs
    to exactly one user (re-registering an existing token REASSIGNS it —
    shared computer, new login).
    """

    class Platform(models.TextChoices):
        WEB = "web", "Web browser"
        ANDROID = "android", "Android"
        IOS = "ios", "iOS"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="push_devices",
    )
    token = models.CharField(max_length=512, unique=True)
    platform = models.CharField(max_length=10, choices=Platform.choices, default=Platform.WEB)

    class Meta:
        ordering = ["-created_at"]  # deterministic pagination

    def __str__(self):
        return f"{self.user} [{self.platform}] …{self.token[-8:]}"


class EmailOutbox(TimeStampedModel):
    """
    The email QUEUE, as a database table (transactional outbox pattern).
    notify() only INSERTs here — inside the caller's transaction, so a
    rollback also un-queues the email. The send_queued_emails command is
    the queue CONSUMER: it picks due PENDING rows, talks SMTP, and either
    marks them SENT or reschedules them with exponential backoff until
    MAX_ATTEMPTS, after which they park as FAILED for a human to inspect.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"  # gave up after MAX_ATTEMPTS

    MAX_ATTEMPTS = 5

    to_email = models.EmailField()
    subject = models.CharField(max_length=255)
    body = models.TextField()

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    # When the worker may (re)try this row. Starts at "now"; each failure
    # pushes it into the future (backoff) so a broken SMTP server isn't
    # hammered every minute by every stuck row.
    next_attempt_at = models.DateTimeField()
    sent_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["next_attempt_at"]
        indexes = [
            # The worker's sweep: WHERE status='pending' AND next_attempt_at <= now().
            models.Index(fields=["status", "next_attempt_at"]),
        ]
        constraints = [
            # A row can't claim delivery without a timestamp (or vice versa).
            models.CheckConstraint(
                condition=(
                    Q(status="sent", sent_at__isnull=False) | (~Q(status="sent") & Q(sent_at=None))
                ),
                name="outbox_sent_at_matches_status",
            ),
        ]

    def __str__(self):
        return f"[{self.status}] {self.subject} → {self.to_email}"
