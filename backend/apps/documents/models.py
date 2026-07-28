"""
Document models (ARCHITECTURE.md §9): one attachment system for every object,
now with version history.

Two-model split — the industry-standard shape for file versioning:

    Document        = the LOGICAL document ("Contract with Acme"), attached to
                      a parent via GenericFK. Never holds bytes itself.
    DocumentVersion = one PHYSICAL file. Uploading a replacement adds a row
                      instead of overwriting — old files stay downloadable,
                      which keeps the audit trail honest (nothing is ever
                      destroyed by an update, matching quotations' revise flow).

`current_version` is a denormalized pointer maintained by services.py so list
screens never have to sort version rows to find "the" file (same trick as the
denormalized totals on quotations/invoices).

The GenericForeignKey trio (content_type + object_id + content_object) lets a
single table attach files to clients, projects, tasks, tickets… — no schema
change per target. Legal targets are whitelisted in apps.core.attachments,
enforced at the serializer.
"""

import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel


def document_upload_path(instance, filename):
    """
    documents/<yyyy>/<mm>/<uuid>.<ext> — stored name is a random UUID (§9).
    The user's original filename can collide, contain "../" tricks, or break
    filesystems; it is kept for display only, in `Document.original_name`.
    """
    ext = filename.rsplit(".", 1)[-1].lower()
    now = timezone.now()
    return f"documents/{now:%Y/%m}/{uuid.uuid4().hex}.{ext}"


class Document(TimeStampedModel):
    original_name = models.CharField(max_length=255)

    # SET_NULL: deleting the uploader must not destroy the client's files;
    # the document simply shows "uploaded by: (removed user)".
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="uploaded_documents",
    )

    # -- GenericFK: which object this file is attached to --------------------
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    # Denormalized "latest" pointer, kept in sync by services. SET_NULL (not
    # CASCADE) because when the whole document is deleted, the collector must
    # be able to clear this before cascading into the versions.
    current_version = models.ForeignKey(
        "DocumentVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        indexes = [
            # THE query of this table: "all documents on client 7".
            models.Index(fields=["content_type", "object_id", "-created_at"]),
        ]

    def __str__(self):
        return self.original_name


class DocumentVersion(TimeStampedModel):
    """
    Append-only: a version row is never edited after creation, only added
    (new upload) or removed (when its parent document is deleted).
    """

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="versions")
    version_number = models.PositiveIntegerField()

    file = models.FileField(upload_to=document_upload_path)
    # Metadata captured at upload so lists never need to touch the disk/bucket.
    mime_type = models.CharField(max_length=100)
    size_bytes = models.PositiveBigIntegerField()

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="uploaded_document_versions",
    )

    class Meta:
        constraints = [
            # Numbering is assigned under a row lock (services.add_version);
            # this constraint is the DB-level backstop against a race slipping
            # through and producing two "version 3"s.
            models.UniqueConstraint(
                fields=["document", "version_number"], name="unique_document_version_number"
            ),
        ]
        ordering = ["-version_number"]

    def __str__(self):
        return f"{self.document_id} v{self.version_number}"
