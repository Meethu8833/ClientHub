from django.contrib import admin

from .models import SlaPolicy, Ticket, TicketCategory, TicketReply


@admin.register(TicketCategory)
class TicketCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["name"]


@admin.register(SlaPolicy)
class SlaPolicyAdmin(admin.ModelAdmin):
    list_display = ["priority", "first_response_minutes", "resolution_minutes"]


class TicketReplyInline(admin.TabularInline):
    model = TicketReply
    extra = 0
    readonly_fields = ["author", "created_at"]


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ["id", "subject", "client", "status", "priority", "assignee", "is_escalated"]
    list_filter = ["status", "priority", "is_escalated", "category"]
    search_fields = ["subject", "description", "client__name"]
    list_select_related = ["client", "assignee"]
    inlines = [TicketReplyInline]
    readonly_fields = [
        "first_response_due_at",
        "resolution_due_at",
        "first_response_at",
        "resolved_at",
        "closed_at",
        "reopened_count",
    ]
