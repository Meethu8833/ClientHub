"""
Notes & Activities (ARCHITECTURE.md §4 — activities app).

A Note is free-form human text pinned to any business object via the same
GenericFK pattern as Document ("called them, renewal likely in Q3").
An Activity is a machine-authored history row ("status changed from X to Y"),
written by services.record() whenever something notable happens. They are
separate models on purpose: notes are editable human knowledge, activities
are an append-only audit trail — mixing them would let history be rewritten.
"""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.core.models import TimeStampedModel


class Note(TimeStampedModel):
    body = models.TextField()
    # SET_NULL: the note (business knowledge) outlives its author's account.
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="notes",
    )

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    class Meta:
        indexes = [
            # "all notes on client 7, newest first" — the only real query.
            models.Index(fields=["content_type", "object_id", "-created_at"]),
        ]

    def __str__(self):
        return f"Note #{self.pk} by {self.author}"


class Activity(TimeStampedModel):
    """
    One history event on one object. APPEND-ONLY: no API updates or deletes,
    ever — an audit trail you can edit is not an audit trail.

    `verb` is a short machine string the frontend maps to display text;
    `changes` holds the event's data as JSON, shaped per verb, e.g.
        status_changed  -> {"field": "status", "from": "planned", "to": "in_progress"}
        member_added    -> {"user_id": 7, "user": "Dev Devi", "role": "developer"}
    JSON (not columns) because every verb needs different data — a column per
    possibility would be a sparse mess.
    """

    class Verb(models.TextChoices):
        CREATED = "created", "Created"
        UPDATED = "updated", "Updated"
        STATUS_CHANGED = "status_changed", "Status changed"
        MEMBER_ADDED = "member_added", "Member added"
        MEMBER_REMOVED = "member_removed", "Member removed"
        MEMBER_ROLE_CHANGED = "member_role_changed", "Member role changed"
        MILESTONE_COMPLETED = "milestone_completed", "Milestone completed"
        MILESTONE_REOPENED = "milestone_reopened", "Milestone reopened"
        # Task events. assigned covers reassign AND unassign (changes carry
        # from/to); task_deleted lands on the PROJECT timeline because the
        # task's own timeline dies with the task.
        ASSIGNED = "assigned", "Assigned"
        TASK_DELETED = "task_deleted", "Task deleted"
        # Sprint ceremonies — on the PROJECT timeline: a sprint is a phase of
        # the project, and start/complete are the events an auditor asks about.
        SPRINT_STARTED = "sprint_started", "Sprint started"
        SPRINT_COMPLETED = "sprint_completed", "Sprint completed"
        # Ticket event: escalation is a flag-raise, not a status move, so it
        # gets its own verb (status changes reuse STATUS_CHANGED).
        ESCALATED = "escalated", "Escalated"
        # Billing events — money moves get their own verbs (not STATUS_CHANGED,
        # which billing also emits): the amount and method belong on the trail.
        PAYMENT_RECORDED = "payment_recorded", "Payment recorded"
        PAYMENT_DELETED = "payment_deleted", "Payment deleted"
        # Payment-management events (all land on the INVOICE timeline — the
        # invoice is the document an auditor walks, payments are its rows).
        PAYMENT_CLEARED = "payment_cleared", "Payment cleared"
        PAYMENT_BOUNCED = "payment_bounced", "Payment bounced"
        REFUND_RECORDED = "refund_recorded", "Refund recorded"
        REFUND_DELETED = "refund_deleted", "Refund deleted"
        # One verb for both directions; changes carries {"reconciled": bool}.
        RECONCILED = "reconciled", "Reconciled"
        # Meeting events. Reschedule is NOT a status move (the meeting stays
        # scheduled) so it gets its own verb; attendee changes mirror the
        # project member verbs but carry {"kind": user|contact}.
        RESCHEDULED = "rescheduled", "Rescheduled"
        MINUTES_RECORDED = "minutes_recorded", "Minutes recorded"
        ATTENDEE_ADDED = "attendee_added", "Attendee added"
        ATTENDEE_REMOVED = "attendee_removed", "Attendee removed"
        DELETED = "deleted", "Deleted"

    verb = models.CharField(max_length=30, choices=Verb.choices)
    changes = models.JSONField(default=dict, blank=True)
    # SET_NULL: history must outlive the person who made it.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="activities",
    )

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    class Meta:
        verbose_name_plural = "activities"
        indexes = [
            # "timeline of project 7, newest first" — the only real query (§4).
            models.Index(fields=["content_type", "object_id", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.verb} on {self.content_type} #{self.object_id}"
