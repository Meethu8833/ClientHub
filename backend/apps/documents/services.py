"""
Document write operations (ARCHITECTURE.md §11: side-effect logic lives in
services, views stay thin).

Both entry points are atomic: a Document without any version, or a version
without the current_version pointer updated, must never be observable.
"""

from django.db import transaction
from django.db.models import Max

from .models import Document, DocumentVersion


@transaction.atomic
def create_document(*, target, file, mime_type, user):
    """Create the logical document and its version 1 in one step."""
    document = Document.objects.create(
        original_name=file.name[:255],
        uploaded_by=user,
        content_object=target,
    )
    _store_version(document, file=file, mime_type=mime_type, user=user, version_number=1)
    return document


@transaction.atomic
def add_version(*, document, file, mime_type, user):
    """
    Append the next version and promote it to current.

    select_for_update: two simultaneous uploads would otherwise both read
    "latest = 2" and both try to write version 3. The row lock serializes
    them; the DB unique constraint is the backstop if a lock is ever bypassed.
    """
    document = Document.objects.select_for_update().get(pk=document.pk)
    latest = document.versions.aggregate(n=Max("version_number"))["n"] or 0
    return _store_version(
        document, file=file, mime_type=mime_type, user=user, version_number=latest + 1
    )


def _store_version(document, *, file, mime_type, user, version_number):
    version = DocumentVersion.objects.create(
        document=document,
        version_number=version_number,
        file=file,
        mime_type=mime_type,
        size_bytes=file.size,
        uploaded_by=user,
    )
    document.current_version = version
    document.save(update_fields=["current_version", "updated_at"])
    return version
