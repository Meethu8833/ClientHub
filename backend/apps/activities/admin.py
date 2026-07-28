from django.contrib import admin

from .models import Note


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ["id", "author", "content_type", "object_id", "created_at"]
    search_fields = ["body"]
