"""
Quotation serializers (§6): slim List for the pipeline table, full Detail
with nested items for the quotation page, a Write serializer that accepts
*_id fields, plus tiny action bodies. `status` and every money total are
read-only EVERYWHERE — the lifecycle moves through actions → services, and
totals are computed from the lines, never accepted from a caller.
"""

from decimal import Decimal

from rest_framework import serializers

from apps.clients.models import Client, Contact

from .models import Quotation, QuotationItem


class UserSlimSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.SerializerMethodField()

    def get_name(self, obj):
        return obj.get_full_name() or obj.email


class QuotationItemSerializer(serializers.ModelSerializer):
    """Read shape: inputs + every computed money stage, so the frontend can
    render the full breakdown without re-implementing the math (one source
    of truth for rounding: the server)."""

    line_subtotal = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    line_discount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    taxable_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    line_tax = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    line_total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = QuotationItem
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


class QuotationItemWriteSerializer(serializers.ModelSerializer):
    """
    POST/PATCH body for a line. min/max mirror the DB CheckConstraints so bad
    input dies as a clean 400, not an IntegrityError 500.
    """

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
        model = QuotationItem
        fields = [
            "description",
            "quantity",
            "unit",
            "unit_price",
            "discount_percent",
            "tax_percent",
            "position",
        ]


class QuotationListSerializer(serializers.ModelSerializer):
    """One pipeline row — what the table shows, nothing more."""

    display_number = serializers.CharField(read_only=True)
    client = serializers.SerializerMethodField()
    created_by = UserSlimSerializer(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = Quotation
        fields = [
            "id",
            "quote_number",
            "version",
            "display_number",
            "title",
            "client",
            "status",
            "currency",
            "grand_total",
            "valid_until",
            "is_expired",
            "created_by",
            "created_at",
        ]

    def get_client(self, obj):
        return {"id": obj.client_id, "name": obj.client.name}


class QuotationDetailSerializer(QuotationListSerializer):
    """The full quotation page: money breakdown, lines, and every trail."""

    contact = serializers.SerializerMethodField()
    approved_by = UserSlimSerializer(read_only=True)
    items = QuotationItemSerializer(many=True, read_only=True)
    # Version chain, both directions: what this was cut from, what replaced it.
    revision_of_id = serializers.IntegerField(read_only=True)
    revision_ids = serializers.SerializerMethodField()

    class Meta(QuotationListSerializer.Meta):
        fields = QuotationListSerializer.Meta.fields + [
            "contact",
            "terms",
            "discount_percent",
            "subtotal",
            "discount_total",
            "tax_total",
            "items",
            "revision_of_id",
            "revision_ids",
            "submitted_at",
            "approved_by",
            "approved_at",
            "approval_note",
            "sent_at",
            "accepted_at",
            "declined_at",
            "decline_reason",
            "updated_at",
        ]

    def get_contact(self, obj):
        if obj.contact_id is None:
            return None
        return {"id": obj.contact_id, "name": obj.contact.name}

    def get_revision_ids(self, obj):
        return [r.pk for r in obj.revisions.all()]


class QuotationWriteSerializer(serializers.ModelSerializer):
    """
    POST/PATCH body (drafts only — the view enforces the draft gate). Writes
    accept plain ids, reads return nested objects (§6). Rules here:

    - client must be live (not soft-deleted) and is IMMUTABLE after creation —
      a quote re-pinned to another company would corrupt both clients' sales
      history (same rule as tickets);
    - contact, if given, must belong to that client;
    - valid_until may not be set in the past (submit re-checks — a draft can
      legitimately AGE past its date, but you can't CHOOSE a dead date).
    """

    client_id = serializers.PrimaryKeyRelatedField(
        source="client", queryset=Client.objects.filter(is_active=True)
    )
    contact_id = serializers.PrimaryKeyRelatedField(
        source="contact", queryset=Contact.objects.all(), required=False, allow_null=True
    )
    discount_percent = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        required=False,
    )

    class Meta:
        model = Quotation
        fields = [
            "client_id",
            "contact_id",
            "title",
            "terms",
            "currency",
            "discount_percent",
            "valid_until",
        ]

    def validate_valid_until(self, value):
        from django.utils import timezone

        if value is not None and value < timezone.localdate():
            raise serializers.ValidationError("The validity date cannot be in the past.")
        return value

    def validate(self, attrs):
        if self.instance is not None and "client" in attrs:
            if attrs["client"].pk != self.instance.client_id:
                raise serializers.ValidationError(
                    {"client_id": "A quotation cannot be moved to another client."}
                )
        client = attrs.get("client", getattr(self.instance, "client", None))
        contact = attrs.get("contact", getattr(self.instance, "contact", None))
        if contact is not None and contact.client_id != client.pk:
            raise serializers.ValidationError(
                {"contact_id": "This contact does not belong to the quotation's client."}
            )
        return attrs


# --- action bodies ----------------------------------------------------------


class ApproveSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class RequestChangesSerializer(serializers.Serializer):
    """'No' without 'why' helps nobody — the note is mandatory."""

    note = serializers.CharField(max_length=255)


class DeclineSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
