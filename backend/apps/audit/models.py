"""
AuditLog (ARCHITECTURE.md §4 — audit trail requirement).

Distinct from activities.Activity on purpose:
- Activity is the BUSINESS timeline shown to users on an object's page
  ("status changed", "member added") — curated, per-object, product feature.
- AuditLog is the SECURITY/COMPLIANCE record ("who did what, when, from
  which IP") — automatic, system-wide, admin-only. It also captures events
  that have no timeline (logins, failed logins, hard deletes) and raw field
  diffs users should not see.

APPEND-ONLY: no API or admin path may update or delete rows. A standalone
created_at instead of TimeStampedModel because updated_at on a row that must
never be updated would be a lie waiting to be believed.
"""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models


class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATED = "created", "Created"
        UPDATED = "updated", "Updated"
        # Soft delete/restore are detected from the diff (is_active flip or
        # deleted_at set/cleared) and get their own verbs — "updated
        # {is_active: false}" would bury the single event auditors ask about.
        SOFT_DELETED = "soft_deleted", "Soft deleted"
        RESTORED = "restored", "Restored"
        DELETED = "deleted", "Deleted"  # hard delete — row is gone from the DB
        LOGIN = "login", "Login"
        LOGIN_FAILED = "login_failed", "Login failed"
        LOGOUT = "logout", "Logout"

    # SET_NULL + the denormalized repr below: the log must outlive the user.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    # str(user) frozen at write time — still readable after the FK goes NULL,
    # and shows the name the actor had THEN, not whatever it is now.
    actor_repr = models.CharField(max_length=254, blank=True)

    action = models.CharField(max_length=20, choices=Action.choices)

    # What was acted on. SET_NULL (not CASCADE like Note/Activity): deleting
    # a content type must never take audit history down with it. object_id is
    # nullable because auth events (login/logout) have no target object.
    content_type = models.ForeignKey(
        ContentType, on_delete=models.SET_NULL, null=True, blank=True
    )
    object_id = models.PositiveBigIntegerField(null=True, blank=True)
    target = GenericForeignKey("content_type", "object_id")
    target_repr = models.CharField(max_length=200, blank=True)

    # Field diff for updates ({"field": {"from": x, "to": y}}), final snapshot
    # for hard deletes, {"email": ...} for failed logins. DjangoJSONEncoder
    # handles the datetimes/Decimals/UUIDs a plain JSONField would choke on.
    changes = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder)

    # Request fingerprint — the "from where" of the audit question.
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    method = models.CharField(max_length=10, blank=True)
    path = models.CharField(max_length=200, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # -id as tiebreaker: auto_now_add has finite resolution, and two rows
        # in the same transaction must still order deterministically.
        ordering = ["-created_at", "-id"]
        indexes = [
            # "history of client 7"  — same shape as the Activity index.
            models.Index(fields=["content_type", "object_id", "-created_at"]),
            # "everything user 3 did last week" — the incident-response query.
            models.Index(fields=["actor", "-created_at"]),
            # "all failed logins today" — the security-monitoring query.
            models.Index(fields=["action", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.action} by {self.actor_repr or 'system'} at {self.created_at}"
