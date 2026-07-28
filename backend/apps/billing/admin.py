from django.contrib import admin

from .models import Invoice, InvoiceItem, Payment, Refund


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 0


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    can_delete = False  # deletion must go through services (status rollback)

    # View-only: amount/status feed the invoice's derived state — editing
    # them here would bypass the row locks and the activity trail.
    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = [
        "display_number",
        "client",
        "status",
        "grand_total",
        "amount_paid",
        "issue_date",
        "due_date",
        "created_by",
    ]
    list_filter = ["status", "currency"]
    search_fields = ["invoice_number", "client__name"]
    inlines = [InvoiceItemInline, PaymentInline]
    # Numbers, money totals and workflow stamps are service-managed —
    # read-only even for superusers poking around the admin.
    readonly_fields = [
        "invoice_number",
        "subtotal",
        "discount_total",
        "tax_total",
        "grand_total",
        "amount_paid",
        "amount_refunded",
        "issue_date",
        "issued_at",
        "paid_at",
        "voided_at",
    ]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """Read-only browsing: every money move must go through services (row
    locks, derived status, activity trail) — the admin is a window, not a door."""

    list_display = ["invoice", "amount", "status", "method", "received_on", "reconciled_at"]
    list_filter = ["status", "method"]
    search_fields = ["reference", "invoice__invoice_number"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = ["payment", "amount", "method", "refunded_on", "reason"]
    search_fields = ["reference", "reason"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
