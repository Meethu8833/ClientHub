"""
Versioning split: Document keeps the identity, DocumentVersion keeps the file.

Hand-ordered — the auto-generated version dropped Document.file BEFORE
creating DocumentVersion, which would have destroyed every stored file path.
Safe order is: create new table -> copy each document's file into a
version-1 row -> point current_version at it -> only then drop old columns.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import apps.documents.models


def copy_files_to_versions(apps, schema_editor):
    Document = apps.get_model("documents", "Document")
    DocumentVersion = apps.get_model("documents", "DocumentVersion")
    for doc in Document.objects.all().iterator():
        version = DocumentVersion.objects.create(
            document_id=doc.pk,
            version_number=1,
            file=doc.file.name,
            mime_type=doc.mime_type,
            size_bytes=doc.size_bytes,
            uploaded_by_id=doc.uploaded_by_id,
        )
        # auto_now_add stamped "now" on create; restore the real upload time.
        DocumentVersion.objects.filter(pk=version.pk).update(
            created_at=doc.created_at, updated_at=doc.updated_at
        )
        doc.current_version_id = version.pk
        doc.save(update_fields=["current_version"])


def copy_versions_back(apps, schema_editor):
    """Reverse: flatten the CURRENT version back onto the document row.
    Older versions (and their files) are abandoned — a reverse migration of a
    versioning feature cannot keep history that the old schema can't hold."""
    Document = apps.get_model("documents", "Document")
    DocumentVersion = apps.get_model("documents", "DocumentVersion")
    for doc in Document.objects.exclude(current_version=None).iterator():
        version = DocumentVersion.objects.get(pk=doc.current_version_id)
        doc.file = version.file.name
        doc.mime_type = version.mime_type
        doc.size_bytes = version.size_bytes
        doc.save(update_fields=["file", "mime_type", "size_bytes"])


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DocumentVersion",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("version_number", models.PositiveIntegerField()),
                (
                    "file",
                    models.FileField(upload_to=apps.documents.models.document_upload_path),
                ),
                ("mime_type", models.CharField(max_length=100)),
                ("size_bytes", models.PositiveBigIntegerField()),
                (
                    "document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="versions",
                        to="documents.document",
                    ),
                ),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="uploaded_document_versions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-version_number"]},
        ),
        migrations.AddField(
            model_name="document",
            name="current_version",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="documents.documentversion",
            ),
        ),
        migrations.AddConstraint(
            model_name="documentversion",
            constraint=models.UniqueConstraint(
                fields=("document", "version_number"), name="unique_document_version_number"
            ),
        ),
        migrations.RunPython(copy_files_to_versions, copy_versions_back),
        migrations.RemoveField(model_name="document", name="file"),
        migrations.RemoveField(model_name="document", name="mime_type"),
        migrations.RemoveField(model_name="document", name="size_bytes"),
    ]
