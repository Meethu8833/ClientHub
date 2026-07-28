"""
Ticket serializers (§6): slim List for the queue table, full Detail for the
ticket page, a Write serializer that accepts *_id fields, plus tiny action
bodies (resolve/escalate/assign). `status` is read-only EVERYWHERE — the
lifecycle moves only through the action endpoints → services state machine.
"""

from rest_framework import serializers

from apps.accounts.models import User
from apps.clients.models import Client, Contact

from .models import SlaPolicy, Ticket, TicketCategory, TicketReply


class UserSlimSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.SerializerMethodField()

    def get_name(self, obj):
        return obj.get_full_name() or obj.email


class TicketCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketCategory
        fields = ["id", "name", "description", "is_active", "created_at"]


class SlaPolicySerializer(serializers.ModelSerializer):
    # min_value mirrors the DB CheckConstraint so bad input dies with a clean
    # 400 instead of an IntegrityError 500.
    first_response_minutes = serializers.IntegerField(min_value=1)
    resolution_minutes = serializers.IntegerField(min_value=1)

    class Meta:
        model = SlaPolicy
        fields = ["id", "priority", "first_response_minutes", "resolution_minutes", "updated_at"]

    def validate(self, attrs):
        # PATCH may send either field alone — fall back to the stored value.
        first = attrs.get("first_response_minutes") or self.instance.first_response_minutes
        resolution = attrs.get("resolution_minutes") or self.instance.resolution_minutes
        if first > resolution:
            raise serializers.ValidationError(
                {"first_response_minutes": "First response cannot be promised after resolution."}
            )
        return attrs


class TicketListSerializer(serializers.ModelSerializer):
    """One queue row: what the table shows, nothing more (§6: never expose
    fields 'because the model has them')."""

    client = serializers.SerializerMethodField()
    assignee = UserSlimSerializer(read_only=True)
    category = serializers.CharField(source="category.name")
    # List queries annotate reply_count (one aggregate for the whole page);
    # mutation responses serialize a plain instance and fall back to one COUNT.
    reply_count = serializers.SerializerMethodField()
    is_first_response_overdue = serializers.BooleanField(read_only=True)
    is_resolution_overdue = serializers.BooleanField(read_only=True)

    class Meta:
        model = Ticket
        fields = [
            "id",
            "subject",
            "status",
            "priority",
            "is_escalated",
            "client",
            "assignee",
            "category",
            "reply_count",
            "first_response_due_at",
            "resolution_due_at",
            "is_first_response_overdue",
            "is_resolution_overdue",
            "created_at",
        ]

    def get_client(self, obj):
        return {"id": obj.client_id, "name": obj.client.name}

    def get_reply_count(self, obj):
        count = getattr(obj, "reply_count", None)
        return count if count is not None else obj.replies.count()


class TicketDetailSerializer(TicketListSerializer):
    """The full ticket page: everything the list shows plus the story."""

    contact = serializers.SerializerMethodField()
    created_by = UserSlimSerializer(read_only=True)
    escalated_by = UserSlimSerializer(read_only=True)
    category = TicketCategorySerializer(read_only=True)

    class Meta(TicketListSerializer.Meta):
        fields = TicketListSerializer.Meta.fields + [
            "description",
            "contact",
            "created_by",
            "escalated_at",
            "escalated_by",
            "escalation_reason",
            "first_response_at",
            "resolved_at",
            "closed_at",
            "resolution_summary",
            "reopened_count",
            "updated_at",
        ]

    def get_contact(self, obj):
        if obj.contact_id is None:
            return None
        return {"id": obj.contact_id, "name": obj.contact.name}


class TicketWriteSerializer(serializers.ModelSerializer):
    """
    POST/PATCH body. Writes accept plain ids (client_id, …) while reads
    return nested objects — the §6 convention. Rules enforced here:

    - client must be a live (non-soft-deleted) client, and is IMMUTABLE after
      creation (a ticket re-pinned to another company would corrupt both
      clients' support history — same rule as notes never changing target);
    - contact, if given, must belong to that client;
    - category must be active for NEW choices; an existing ticket may keep a
      since-retired category.
    """

    client_id = serializers.PrimaryKeyRelatedField(
        source="client", queryset=Client.objects.filter(is_active=True)
    )
    contact_id = serializers.PrimaryKeyRelatedField(
        source="contact",
        queryset=Contact.objects.all(),
        required=False,
        allow_null=True,
    )
    category_id = serializers.PrimaryKeyRelatedField(
        source="category", queryset=TicketCategory.objects.all()
    )
    assignee_id = serializers.PrimaryKeyRelatedField(
        source="assignee",
        queryset=User.objects.all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = Ticket
        fields = [
            "client_id",
            "contact_id",
            "category_id",
            "assignee_id",
            "subject",
            "description",
            "priority",
        ]

    def validate_assignee_id(self, user):
        if user is not None and user.deleted_at is not None:
            raise serializers.ValidationError("This user no longer exists.")
        return user

    def validate_category_id(self, category):
        # Only NEW choices must be active: keeping a retired category is fine.
        if self.instance is not None and category.pk == self.instance.category_id:
            return category
        if not category.is_active:
            raise serializers.ValidationError("This category has been retired.")
        return category

    def validate(self, attrs):
        if self.instance is not None and "client" in attrs:
            if attrs["client"].pk != self.instance.client_id:
                raise serializers.ValidationError(
                    {"client_id": "A ticket cannot be moved to another client."}
                )
        client = attrs.get("client", getattr(self.instance, "client", None))
        contact = attrs.get("contact", getattr(self.instance, "contact", None))
        if contact is not None and contact.client_id != client.pk:
            raise serializers.ValidationError(
                {"contact_id": "This contact does not belong to the ticket's client."}
            )
        return attrs


class TicketReplySerializer(serializers.ModelSerializer):
    author = UserSlimSerializer(read_only=True)

    class Meta:
        model = TicketReply
        fields = ["id", "author", "body", "is_internal", "created_at"]


class TicketReplyCreateSerializer(serializers.Serializer):
    """POST body for a reply — ticket comes from the URL, author from the JWT."""

    body = serializers.CharField()
    is_internal = serializers.BooleanField(default=False)


# --- action bodies ----------------------------------------------------------


class ResolveSerializer(serializers.Serializer):
    """A resolution without a summary is not a resolution."""

    summary = serializers.CharField()


class EscalateSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class AssignSerializer(serializers.Serializer):
    """{assignee_id: 7} to hand over, {assignee_id: null} to send back to queue."""

    assignee_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(deleted_at__isnull=True), allow_null=True
    )
