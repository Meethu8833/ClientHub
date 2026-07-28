from django.contrib import admin

from .models import Quotation, QuotationItem


class QuotationItemInline(admin.TabularInline):
    model = QuotationItem
    extra = 0


@admin.register(Quotation)
class QuotationAdmin(admin.ModelAdmin):
    list_display = [
        "display_number",
        "title",
        "client",
        "status",
        "grand_total",
        "valid_until",
        "created_by",
    ]
    list_filter = ["status", "currency"]
    search_fields = ["quote_number", "title", "client__name"]
    inlines = [QuotationItemInline]
    # Money totals and workflow stamps are service-managed — read-only even
    # for superusers poking around the admin.
    readonly_fields = [
        "quote_number",
        "version",
        "subtotal",
        "discount_total",
        "tax_total",
        "grand_total",
        "submitted_at",
        "approved_at",
        "sent_at",
        "accepted_at",
        "declined_at",
    ]
