from django.contrib import admin

from .models import ActionItem, Meeting, MeetingAttendee, MeetingMinutes, MeetingReminder


class AttendeeInline(admin.TabularInline):
    model = MeetingAttendee
    extra = 0
    readonly_fields = ["response", "responded_at"]


class ReminderInline(admin.TabularInline):
    model = MeetingReminder
    extra = 0
    readonly_fields = ["remind_at", "sent_at"]


@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ["id", "title", "client", "organizer", "scheduled_start", "status", "mode"]
    list_filter = ["status", "mode"]
    search_fields = ["title", "agenda", "client__name"]
    list_select_related = ["client", "organizer"]
    inlines = [AttendeeInline, ReminderInline]
    readonly_fields = ["completed_at", "cancelled_at", "cancelled_by", "rescheduled_count"]


@admin.register(MeetingMinutes)
class MeetingMinutesAdmin(admin.ModelAdmin):
    list_display = ["meeting", "recorded_by", "updated_at"]


@admin.register(ActionItem)
class ActionItemAdmin(admin.ModelAdmin):
    list_display = ["description", "meeting", "owner", "due_date", "is_done"]
    list_filter = ["is_done"]
