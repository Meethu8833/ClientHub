"""
Serializers for clients & contacts (ARCHITECTURE.md §6 conventions):

- ClientListSerializer   — slim rows for the table screen
- ClientDetailSerializer — full record + nested account_manager + contacts
- ClientWriteSerializer  — what POST/PATCH accept (writes take _id fields)
- Contact serializers    — same split, smaller

Never expose fields "because the model has them": each shape is deliberate.
"""

from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Client, Contact

User = get_user_model()


class AccountManagerSerializer(serializers.ModelSerializer):
    """Mini user representation embedded in client reads: {id, name, email}."""

    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "name", "email"]

    def get_name(self, obj):
        return obj.get_full_name() or obj.email


class ContactSerializer(serializers.ModelSerializer):
    """Read shape for contacts (nested under client detail and flat GETs)."""

    class Meta:
        model = Contact
        fields = [
            "id",
            "client",
            "name",
            "email",
            "phone",
            "position",
            "is_primary",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ContactWriteSerializer(serializers.ModelSerializer):
    """
    Write shape. `client` is intentionally absent: on nested create the view
    injects it from the URL (/clients/{id}/contacts/), and on update a contact
    can never be moved between companies — that's a new contact, not an edit.
    """

    class Meta:
        model = Contact
        fields = ["name", "email", "phone", "position", "is_primary"]

    def save(self, **kwargs):
        # Route every write through the service so the "demote the old
        # primary" invariant holds no matter which endpoint saved.
        from . import services

        instance = self.instance or Contact(**kwargs)
        for attr, value in self.validated_data.items():
            setattr(instance, attr, value)
        self.instance = services.save_contact(instance)
        return self.instance


class ClientListSerializer(serializers.ModelSerializer):
    """One table row: enough to render the list, nothing more (fast query)."""

    account_manager = AccountManagerSerializer(read_only=True)
    # Annotated in the viewset's get_queryset (COUNT in SQL, no N+1).
    contact_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Client
        fields = [
            "id",
            "name",
            "industry",
            "city",
            "status",
            "account_manager",
            "contact_count",
            "created_at",
        ]


class ClientDetailSerializer(serializers.ModelSerializer):
    """Full record for the detail page, contacts included (prefetched)."""

    account_manager = AccountManagerSerializer(read_only=True)
    contacts = ContactSerializer(many=True, read_only=True)

    class Meta:
        model = Client
        fields = [
            "id",
            "name",
            "industry",
            "website",
            "email",
            "phone",
            "gst_number",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "postal_code",
            "country",
            "status",
            "account_manager",
            "contacts",
            "created_at",
            "updated_at",
        ]


class ClientWriteSerializer(serializers.ModelSerializer):
    """
    POST/PATCH body. Reads embed account_manager as an object; writes accept
    a plain id under `account_manager_id` (§6: "writes accept _id fields").
    """

    account_manager_id = serializers.PrimaryKeyRelatedField(
        source="account_manager",
        queryset=User.objects.none(),  # real queryset set in __init__
        required=False,
        allow_null=True,
    )

    class Meta:
        model = Client
        fields = [
            "name",
            "industry",
            "website",
            "email",
            "phone",
            "gst_number",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "postal_code",
            "country",
            "status",
            "account_manager_id",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Soft-deleted users can't be handed a book of business. Set here
        # (not in the field declaration) so the queryset is evaluated per
        # request, never cached at import time.
        self.fields["account_manager_id"].queryset = User.objects.alive()

    def to_internal_value(self, data):
        # Normalize BEFORE field validation: the model's GSTIN RegexValidator
        # runs during to_internal_value, so "29abcde1234f1z5 " must already be
        # "29ABCDE1234F1Z5" by then, or a merely-lowercase GSTIN would 400.
        if isinstance(data.get("gst_number"), str):
            data = data.copy()  # request data is immutable (QueryDict)
            data["gst_number"] = data["gst_number"].strip().upper()
        return super().to_internal_value(data)

    def validate_gst_number(self, value):
        if (
            value
            and Client.objects.exclude(pk=getattr(self.instance, "pk", None))
            .filter(gst_number=value)
            .exists()
        ):
            # Friendly 400 now; the DB constraint stays as the racy-write backstop.
            raise serializers.ValidationError("A client with this GSTIN already exists.")
        return value
