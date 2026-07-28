from django.contrib import admin

from .models import EmailOutbox, Notification, NotificationPreference, PushDevice


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["id", "recipient", "category", "title", "read_at", "created_at"]
    list_filter = ["category"]
    search_fields = ["title", "recipient__email"]
    raw_id_fields = ["recipient", "actor"]


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ["user", "category", "in_app_enabled", "email_enabled", "push_enabled"]
    list_filter = ["category"]
    raw_id_fields = ["user"]


@admin.register(PushDevice)
class PushDeviceAdmin(admin.ModelAdmin):
    list_display = ["user", "platform", "created_at"]
    raw_id_fields = ["user"]


@admin.register(EmailOutbox)
class EmailOutboxAdmin(admin.ModelAdmin):
    """The support view for 'why didn't the client get the email?'."""

    list_display = ["id", "to_email", "subject", "status", "attempts", "next_attempt_at", "sent_at"]
    list_filter = ["status"]
    search_fields = ["to_email", "subject"]
    readonly_fields = ["attempts", "last_error", "sent_at"]
