"""
Orphan-file sweep (ARCHITECTURE.md §9) — run by cron, e.g. nightly:

    python manage.py sweep_orphan_files            # delete orphans >24h old
    python manage.py sweep_orphan_files --dry-run  # report only

An orphan is a file under documents/ that no DocumentVersion row references.
They appear when an upload's transaction rolls back AFTER the storage write
(Django writes the file before COMMIT), or if a delete signal ever fails.
The DB is the source of truth; storage is reconciled to match it.

Walks the DEFAULT storage backend, so the same command works on local disk
and on S3. The age guard exists because storage-write-then-DB-commit means a
brand-new file can look orphaned for the split second before its row lands —
never sweep anything younger than --min-age-hours.
"""

from datetime import timedelta

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.documents.models import DocumentVersion

DOCUMENTS_PREFIX = "documents"


def walk(storage, path):
    """Yield every file name under `path`, recursively. Storage backends only
    offer listdir() (one level), so recursion is on us."""
    directories, files = storage.listdir(path)
    for name in files:
        yield f"{path}/{name}"
    for directory in directories:
        yield from walk(storage, f"{path}/{directory}")


class Command(BaseCommand):
    help = "Delete files under documents/ that no DocumentVersion row references."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="Report orphans without deleting."
        )
        parser.add_argument(
            "--min-age-hours",
            type=int,
            default=24,
            help="Never touch files younger than this (default 24) — they may "
            "belong to an upload whose DB row hasn't committed yet.",
        )

    def handle(self, *args, **options):
        storage = default_storage
        try:
            names = list(walk(storage, DOCUMENTS_PREFIX))
        except FileNotFoundError:
            self.stdout.write("No documents/ directory yet — nothing to sweep.")
            return

        # One query, one set: membership checks are O(1) even with millions
        # of files. Never query per-file.
        referenced = set(DocumentVersion.objects.values_list("file", flat=True))
        cutoff = timezone.now() - timedelta(hours=options["min_age_hours"])

        deleted = skipped_young = 0
        for name in names:
            if name in referenced:
                continue
            modified = storage.get_modified_time(name)
            if modified > cutoff:
                skipped_young += 1
                continue
            if options["dry_run"]:
                self.stdout.write(f"[dry-run] would delete {name}")
            else:
                storage.delete(name)
                self.stdout.write(f"deleted {name}")
            deleted += 1

        verb = "would delete" if options["dry_run"] else "deleted"
        self.stdout.write(
            self.style.SUCCESS(
                f"Swept {len(names)} file(s): {verb} {deleted} orphan(s), "
                f"kept {len(names) - deleted - skipped_young} referenced, "
                f"skipped {skipped_young} too-new."
            )
        )
