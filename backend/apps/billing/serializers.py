"""
Billing serializers (§6): slim List for the billing table, full Detail with
nested items + payments, a Write serializer that accepts *_id fields, plus
tiny action bodies. `status`, every money total, `amount_paid` and the whole
date/number trail are read-only EVERYWHERE — the lifecycle moves through
actions → services, and paid state is derived from Payment rows, never typed.
"""

from decimal import Decimal

from rest_framework import serializers

from apps.clients.models import Client, Contact
from apps.projects.models import Project
from apps.quotations.models import Quotation

from .models import Invoice, InvoiceItem, Payment, Refund


class UserSlimSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.SerializerMethodField()

    def get_name(self, obj):
        return obj.get_full_name() or obj.email


class InvoiceItemSerializer(serializers.ModelSerializer):
    """Read shape: inputs + every computed money stage — the server is the
    single source of truth for rounding."""

    line_subtotal = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    line_discount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    taxable_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    line_tax = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    line_total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = InvoiceItem
        fields = [
            "id",
            "description",
            "quantity",
            "unit",
            "unit_price",
            "discount_percent",
            "tax_percent",
            "position",
            "line_subtotal",
            "line_discount",
            "taxable_amount",
            "line_tax",
            "line_total",
        ]


class InvoiceItemWriteSerializer(serializers.ModelSerializer):
    """POST/PATCH body for a line. min/max mirror the DB CheckConstraints so
    bad input dies as a clean 400, not an IntegrityError 500."""

    quantity = serializers.DecimalField(max_digits=8, decimal_places=2, min_value=Decimal("0.01"))
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"))
    discount_percent = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        required=False,
    )
    tax_percent = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        required=False,
    )

    class Meta:
        model = InvoiceItem
        fields = [
            "description",
            "quantity",
            "unit",
            "unit_price",
            "discount_percent",
            "tax_percent",
            "position",
        ]


class RefundSerializer(serializers.ModelSerializer):
    recorded_by = UserSlimSerializer(read_only=True)

    class Meta:
        model = Refund
        fields = [
            "id",
            "payment_id",
            "amount",
            "refunded_on",
            "method",
            "reference",
            "reason",
            "recorded_by",
            "created_at",
        ]


class RefundWriteSerializer(serializers.ModelSerializer):
    """POST body for sending money back. The per-payment cap lives in
    services (it needs the row lock); shape checks live here. `reason` is a
    required model field, so DRF already refuses a blank one — same
    money-needs-a-why rule as voiding."""

    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))

    class Meta:
        model = Refund
        fields = ["amount", "refunded_on", "method", "reference", "reason"]

    def validate_refunded_on(self, value):
        from django.utils import timezone

        if value > timezone.localdate():
            raise serializers.ValidationError("The refund date cannot be in the future.")
        return value


class PaymentSerializer(serializers.ModelSerializer):
    recorded_by = UserSlimSerializer(read_only=True)
    reconciled_by = UserSlimSerializer(read_only=True)
    is_reconciled = serializers.BooleanField(read_only=True)
    amount_refunded = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    refundable_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    refunds = RefundSerializer(many=True, read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "amount",
            "received_on",
            "method",
            "status",
            "reference",
            "notes",
            "recorded_by",
            "is_reconciled",
            "reconciled_at",
            "reconciled_by",
            "amount_refunded",
            "refundable_amount",
            "refunds",
            "created_at",
        ]


class PaymentListSerializer(PaymentSerializer):
    """One row of the global payments register (/payments/): the receipt plus
    enough invoice identity to work a bank statement without clicking away."""

    invoice = serializers.SerializerMethodField()

    class Meta(PaymentSerializer.Meta):
        fields = PaymentSerializer.Meta.fields + ["invoice"]

    def get_invoice(self, obj):
        return {
            "id": obj.invoice_id,
            "number": obj.invoice.display_number,
            "client": {"id": obj.invoice.client_id, "name": obj.invoice.client.name},
        }


class PaymentWriteSerializer(serializers.ModelSerializer):
    """POST body for recording money. The overpayment check lives in services
    (it needs the row lock); the shape checks live here. `status` may only be
    pending or completed — bounced is an OUTCOME (reached via the bounce
    action), never a starting point."""

    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    status = serializers.ChoiceField(
        choices=[Payment.Status.PENDING, Payment.Status.COMPLETED],
        required=False,
        default=Payment.Status.COMPLETED,
    )

    class Meta:
        model = Payment
        fields = ["amount", "received_on", "method", "status", "reference", "notes"]

    def validate_received_on(self, value):
        from django.utils import timezone

        # Money that hasn't arrived yet isn't a receipt — it's a hope.
        if value > timezone.localdate():
            raise serializers.ValidationError("The received date cannot be in the future.")
        return value


class InvoiceListSerializer(serializers.ModelSerializer):
    """One billing-table row: identity, state, and the three numbers every
    billing screen lives on (total, paid, balance)."""

    display_number = serializers.CharField(read_only=True)
    client = serializers.SerializerMethodField()
    net_paid = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    balance_due = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    days_overdue = serializers.IntegerField(read_only=True)
    created_by = UserSlimSerializer(read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id",
            "invoice_number",
            "display_number",
            "client",
            "status",
            "currency",
            "grand_total",
            "amount_paid",
            "amount_refunded",
            "net_paid",
            "balance_due",
            "issue_date",
            "due_date",
            "is_overdue",
            "days_overdue",
            "created_by",
            "created_at",
        ]

    def get_client(self, obj):
        return {"id": obj.client_id, "name": obj.client.name}


class InvoiceDetailSerializer(InvoiceListSerializer):
    """The full invoice page: money breakdown, lines, payments, every trail."""

    contact = serializers.SerializerMethodField()
    project = serializers.SerializerMethodField()
    quotation_id = serializers.IntegerField(read_only=True)
    items = InvoiceItemSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)

    class Meta(InvoiceListSerializer.Meta):
        fields = InvoiceListSerializer.Meta.fields + [
            "contact",
            "project",
            "quotation_id",
            "payment_terms_days",
            "terms",
            "notes",
            "discount_percent",
            "subtotal",
            "discount_total",
            "tax_total",
            "items",
            "payments",
            "issued_at",
            "paid_at",
            "voided_at",
            "void_reason",
            "updated_at",
        ]

    def get_contact(self, obj):
        if obj.contact_id is None:
            return None
        return {"id": obj.contact_id, "name": obj.contact.name}

    def get_project(self, obj):
        if obj.project_id is None:
            return None
        return {"id": obj.project_id, "name": obj.project.name}


class InvoiceWriteSerializer(serializers.ModelSerializer):
    """
    POST/PATCH body (drafts only — the view enforces the draft gate). Rules:

    - client must be live and is IMMUTABLE after creation — re-pinning a bill
      to another company would corrupt both clients' books (tickets rule);
    - contact and project, if given, must belong to that client;
    - due_date may not be set in the past (issue re-checks — a draft can age).
    """

    client_id = serializers.PrimaryKeyRelatedField(
        source="client", queryset=Client.objects.filter(is_active=True)
    )
    contact_id = serializers.PrimaryKeyRelatedField(
        source="contact", queryset=Contact.objects.all(), required=False, allow_null=True
    )
    project_id = serializers.PrimaryKeyRelatedField(
        source="project",
        queryset=Project.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    discount_percent = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        required=False,
    )

    class Meta:
        model = Invoice
        fields = [
            "client_id",
            "contact_id",
            "project_id",
            "currency",
            "discount_percent",
            "payment_terms_days",
            "due_date",
            "terms",
            "notes",
        ]

    def validate_due_date(self, value):
        from django.utils import timezone

        if value is not None and value < timezone.localdate():
            raise serializers.ValidationError("The due date cannot be in the past.")
        return value

    def validate(self, attrs):
        if self.instance is not None and "client" in attrs:
            if attrs["client"].pk != self.instance.client_id:
                raise serializers.ValidationError(
                    {"client_id": "An invoice cannot be moved to another client."}
                )
        client = attrs.get("client", getattr(self.instance, "client", None))
        contact = attrs.get("contact", getattr(self.instance, "contact", None))
        project = attrs.get("project", getattr(self.instance, "project", None))
        if contact is not None and contact.client_id != client.pk:
            raise serializers.ValidationError(
                {"contact_id": "This contact does not belong to the invoice's client."}
            )
        if project is not None and project.client_id != client.pk:
            raise serializers.ValidationError(
                {"project_id": "This project does not belong to the invoice's client."}
            )
        return attrs


# --- action bodies ----------------------------------------------------------


class VoidSerializer(serializers.Serializer):
    """Burning a legal number without saying why is an audit red flag —
    the reason is mandatory."""

    reason = serializers.CharField(max_length=255)


class FromQuotationSerializer(serializers.Serializer):
    quotation_id = serializers.PrimaryKeyRelatedField(
        source="quotation", queryset=Quotation.objects.all()
    )
