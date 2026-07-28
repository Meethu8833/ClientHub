from django.contrib import admin

from .models import Document, DocumentVersion


class DocumentVersionInline(admin.TabularInline):
    """Read-only history browser — versions are created via the API/services
    (which assign numbers under a lock), never hand-edited in admin."""

    model = DocumentVersion
    extra = 0
    can_delete = False
    readonly_fields = ["version_number", "file", "mime_type", "size_bytes", "uploaded_by"]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = [
        "original_name",
        "current_version",
        "uploaded_by",
        "content_type",
        "object_id",
        "created_at",
    ]
    search_fields = ["original_name"]
    inlines = [DocumentVersionInline]
