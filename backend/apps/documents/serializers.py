"""
Upload validation (ARCHITECTURE.md §9) — ALL of it server-side. The frontend
may pre-check for UX, but the browser is enemy territory: anything can be
sent with curl.

Three independent gates, in order (cheapest first), shared by BOTH upload
paths (new document and new version):
1. size        ≤ 20 MB (Nginx also caps the body earlier, in prod)
2. extension   whitelist — no .exe, no .svg (SVG executes scripts in browsers)
3. content     libmagic sniffs the BYTES and must agree with the extension —
               "virus.exe renamed to report.pdf" dies here.
"""

import magic
from rest_framework import serializers

from apps.core import attachments

from . import services
from .models import Document, DocumentVersion

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB

# extension -> MIME types libmagic may legitimately report for it.
# docx/xlsx ARE zip archives, so some libmagic builds say application/zip.
ALLOWED_TYPES = {
    "pdf": {"application/pdf"},
    "docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
    },
    "xlsx": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/zip",
    },
    "csv": {"text/csv", "text/plain", "application/csv"},
    "png": {"image/png"},
    "jpg": {"image/jpeg"},
    "jpeg": {"image/jpeg"},
    "zip": {"application/zip"},
}


def run_upload_gates(f):
    """The three gates. Returns the SNIFFED mime type (never trust the
    client's Content-Type header) or raises ValidationError."""
    # Gate 1: size.
    if f.size > MAX_UPLOAD_BYTES:
        raise serializers.ValidationError(
            f"File too large ({f.size} bytes). Maximum is {MAX_UPLOAD_BYTES} (20 MB)."
        )

    # Gate 2: extension whitelist.
    name = f.name or ""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED_TYPES:
        allowed = ", ".join(sorted(ALLOWED_TYPES))
        raise serializers.ValidationError(f"File type '.{ext}' not allowed. Use: {allowed}.")

    # Gate 3: the bytes must agree with the extension. Read the first 2 KB
    # (plenty for magic numbers), then rewind so the storage backend saves
    # the whole file, not a file whose read pointer is at byte 2048.
    sniffed = magic.Magic(mime=True).from_buffer(f.read(2048))
    f.seek(0)
    if sniffed not in ALLOWED_TYPES[ext]:
        raise serializers.ValidationError(
            f"File content ({sniffed}) does not match its .{ext} extension."
        )
    return sniffed


class UploaderSerializer(serializers.Serializer):
    """Mini shape for `uploaded_by` in reads: {id, name}. Null if user removed."""

    id = serializers.IntegerField()
    name = serializers.SerializerMethodField()

    def get_name(self, obj):
        return obj.get_full_name() or obj.email


class DocumentSerializer(serializers.ModelSerializer):
    """Read shape. File metadata comes from the CURRENT version; `target`
    echoes what the file is attached to."""

    uploaded_by = UploaderSerializer(read_only=True)
    target = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()
    mime_type = serializers.SerializerMethodField()
    size_bytes = serializers.SerializerMethodField()
    version = serializers.SerializerMethodField()
    versions_count = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            "id",
            "original_name",
            "mime_type",
            "size_bytes",
            "version",
            "versions_count",
            "uploaded_by",
            "target",
            "download_url",
            "created_at",
            "updated_at",
        ]

    def get_target(self, obj):
        slug = attachments.slug_for_model(obj.content_type.model_class())
        return {"content_type": slug, "object_id": obj.object_id}

    def get_download_url(self, obj):
        # Relative API path — never a direct /media/ URL (§9: media is private).
        return f"/api/v1/documents/{obj.pk}/download/"

    def get_mime_type(self, obj):
        return obj.current_version.mime_type if obj.current_version else None

    def get_size_bytes(self, obj):
        return obj.current_version.size_bytes if obj.current_version else None

    def get_version(self, obj):
        return obj.current_version.version_number if obj.current_version else None

    def get_versions_count(self, obj):
        # The viewset annotates this (one query for the whole list); the
        # getattr fallback covers internal callers that didn't.
        n = getattr(obj, "versions_count", None)
        return n if n is not None else obj.versions.count()


class DocumentVersionSerializer(serializers.ModelSerializer):
    """One row of the version history."""

    uploaded_by = UploaderSerializer(read_only=True)
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = DocumentVersion
        fields = [
            "id",
            "version_number",
            "mime_type",
            "size_bytes",
            "uploaded_by",
            "download_url",
            "created_at",
        ]

    def get_download_url(self, obj):
        return f"/api/v1/documents/{obj.document_id}/download/?version={obj.version_number}"


class DocumentUploadSerializer(serializers.Serializer):
    """
    POST /documents/ multipart body:
        file=<binary>  content_type=client  object_id=7
    Not a ModelSerializer: half the model row (mime, size, uploader, target)
    is DERIVED here, not accepted from the caller.
    """

    file = serializers.FileField()
    content_type = serializers.ChoiceField(choices=attachments.attachable_slugs())
    object_id = serializers.IntegerField(min_value=1)

    def validate_file(self, f):
        self._sniffed_mime = run_upload_gates(f)
        return f

    def validate(self, attrs):
        # Cross-field: the target object must exist and be visible (soft-
        # deleted parents count as missing — no attaching to dead clients).
        target = attachments.get_visible_target(
            attrs["content_type"], attrs["object_id"], user=self.context["request"].user
        )
        if target is None:
            raise serializers.ValidationError(
                {"object_id": f"No {attrs['content_type']} with id {attrs['object_id']}."}
            )
        attrs["target"] = target
        return attrs

    def create(self, validated_data):
        return services.create_document(
            target=validated_data["target"],
            file=validated_data["file"],
            mime_type=self._sniffed_mime,  # trust the sniff, never the client header
            user=self.context["request"].user,
        )


class DocumentVersionUploadSerializer(serializers.Serializer):
    """POST /documents/{id}/versions/ — just the file; the document is the URL."""

    file = serializers.FileField()

    def validate_file(self, f):
        self._sniffed_mime = run_upload_gates(f)
        return f

    def create(self, validated_data):
        return services.add_version(
            document=self.context["document"],
            file=validated_data["file"],
            mime_type=self._sniffed_mime,
            user=self.context["request"].user,
        )
