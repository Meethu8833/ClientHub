"""
Meeting serializers (§6): slim List for the calendar/table, full Detail for
the meeting page, a Write serializer that accepts *_id fields, plus small
action bodies (reschedule/cancel/respond). `status` and every timestamp are
read-only — the lifecycle moves only through the action endpoints → services.
"""

from django.utils import timezone
from rest_framework import serializers

from apps.accounts.models import User
from apps.clients.models import Client, Contact
from apps.projects.models import Project

from .models import ActionItem, Meeting, MeetingAttendee, MeetingMinutes, MeetingReminder


class UserSlimSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.SerializerMethodField()

    def get_name(self, obj):
        return obj.get_full_name() or obj.email


class AttendeeSerializer(serializers.ModelSerializer):
    """
    One attendee row, read shape. `kind` + one flat `person` dict instead of
    exposing the raw user/contact FKs: the frontend renders one list and
    should not care which table the human lives in.
    """

    kind = serializers.SerializerMethodField()
    person = serializers.SerializerMethodField()

    class Meta:
        model = MeetingAttendee
        fields = ["id", "kind", "person", "is_required", "response", "responded_at"]

    def get_kind(self, obj):
        return "user" if obj.user_id else "contact"

    def get_person(self, obj):
        if obj.user_id:
            return {
                "id": obj.user_id,
                "name": obj.user.get_full_name() or obj.user.email,
                "email": obj.user.email,
            }
        return {"id": obj.contact_id, "name": obj.contact.name, "email": obj.contact.email}


class ReminderSerializer(serializers.ModelSerializer):
    class Meta:
        model = MeetingReminder
        fields = ["id", "offset_minutes", "remind_at", "sent_at"]


class MeetingListSerializer(serializers.ModelSerializer):
    """One calendar/table row — what the grid shows, nothing more."""

    client = serializers.SerializerMethodField()
    organizer = UserSlimSerializer(read_only=True)
    duration_minutes = serializers.IntegerField(read_only=True)
    # Annotated on list queries (one aggregate per page); mutation responses
    # serialize a plain instance and fall back to one COUNT.
    attendee_count = serializers.SerializerMethodField()

    class Meta:
        model = Meeting
        fields = [
            "id",
            "title",
            "status",
            "mode",
            "scheduled_start",
            "scheduled_end",
            "duration_minutes",
            "location",
            "client",
            "organizer",
            "attendee_count",
            "rescheduled_count",
        ]

    def get_client(self, obj):
        if obj.client_id is None:
            return None
        return {"id": obj.client_id, "name": obj.client.name}

    def get_attendee_count(self, obj):
        count = getattr(obj, "attendee_count", None)
        return count if count is not None else obj.attendees.count()


class MeetingDetailSerializer(MeetingListSerializer):
    """The full meeting page: the list row plus everyone and everything."""

    project = serializers.SerializerMethodField()
    attendees = AttendeeSerializer(many=True, read_only=True)
    reminders = ReminderSerializer(many=True, read_only=True)
    cancelled_by = UserSlimSerializer(read_only=True)
    # A flag, not the content — minutes have their own endpoint; the page
    # only needs to know whether to show "View minutes" or "Record minutes".
    has_minutes = serializers.SerializerMethodField()

    class Meta(MeetingListSerializer.Meta):
        fields = MeetingListSerializer.Meta.fields + [
            "agenda",
            "meeting_link",
            "project",
            "attendees",
            "reminders",
            "completed_at",
            "cancelled_at",
            "cancelled_by",
            "cancel_reason",
            "has_minutes",
            "created_at",
            "updated_at",
        ]

    def get_project(self, obj):
        if obj.project_id is None:
            return None
        return {"id": obj.project_id, "name": obj.project.name}

    def get_has_minutes(self, obj):
        return MeetingMinutes.objects.filter(meeting_id=obj.pk).exists()


class MeetingWriteSerializer(serializers.ModelSerializer):
    """
    POST/PATCH body. Writes accept ids, reads return nested objects (§6).
    Create also takes the initial attendee lists and reminder offsets —
    afterwards those collections change ONLY via their own endpoints, and
    times change only via /reschedule/ (so side effects can't be skipped).
    """

    client_id = serializers.PrimaryKeyRelatedField(
        source="client",
        queryset=Client.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    project_id = serializers.PrimaryKeyRelatedField(
        source="project",
        queryset=Project.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    # write_only: these shape the CREATE only; reads show nested attendees.
    attendee_user_ids = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(deleted_at__isnull=True),
        many=True,
        required=False,
        write_only=True,
    )
    attendee_contact_ids = serializers.PrimaryKeyRelatedField(
        queryset=Contact.objects.all(), many=True, required=False, write_only=True
    )
    # Minutes-before-start, default "a day before and an hour before" — the
    # convention every mainstream calendar tool ships with.
    reminder_offsets = serializers.ListField(
        child=serializers.IntegerField(min_value=1, max_value=20160),  # ≤ 2 weeks
        required=False,
        default=[1440, 60],
        max_length=5,
        write_only=True,
    )

    class Meta:
        model = Meeting
        fields = [
            "title",
            "agenda",
            "client_id",
            "project_id",
            "mode",
            "location",
            "meeting_link",
            "scheduled_start",
            "scheduled_end",
            "attendee_user_ids",
            "attendee_contact_ids",
            "reminder_offsets",
        ]

    def validate(self, attrs):
        if self.instance is not None:
            # PATCH = scalar edits only. Times move through /reschedule/
            # (which resets RSVPs and re-stamps reminders); collections
            # through their own endpoints. Silently accepting them here
            # would skip those side effects.
            for field in ("scheduled_start", "scheduled_end"):
                if field in attrs:
                    raise serializers.ValidationError(
                        {field: "Times change via POST /meetings/{id}/reschedule/."}
                    )
            for field in ("attendee_user_ids", "attendee_contact_ids", "reminder_offsets"):
                if field in self.initial_data:
                    raise serializers.ValidationError(
                        {field: "Manage this via the attendees/reminders endpoints."}
                    )
            return attrs

        start, end = attrs["scheduled_start"], attrs["scheduled_end"]
        if end <= start:
            raise serializers.ValidationError(
                {"scheduled_end": "The meeting must end after it starts."}
            )
        if start <= timezone.now():
            raise serializers.ValidationError(
                {"scheduled_start": "Meetings are scheduled in the future."}
            )

        # A project meeting is implicitly a meeting with that project's
        # client — derive it rather than making the caller repeat themselves.
        project, client = attrs.get("project"), attrs.get("client")
        if project is not None:
            if client is None:
                attrs["client"] = client = project.client
            elif project.client_id != client.pk:
                raise serializers.ValidationError(
                    {"project_id": "This project does not belong to the selected client."}
                )

        # Contact attendees only make sense on a client meeting, and only
        # the client's own people can be invited on its behalf.
        contacts = attrs.get("attendee_contact_ids", [])
        if contacts and client is None:
            raise serializers.ValidationError(
                {"attendee_contact_ids": "Contact attendees require a client on the meeting."}
            )
        for contact in contacts:
            if contact.client_id != client.pk:
                raise serializers.ValidationError(
                    {
                        "attendee_contact_ids": (
                            f"Contact '{contact.name}' does not belong to this client."
                        )
                    }
                )

        offsets = attrs.get("reminder_offsets", [])
        if len(set(offsets)) != len(offsets):
            raise serializers.ValidationError({"reminder_offsets": "Offsets must be unique."})
        return attrs


class AttendeeCreateSerializer(serializers.Serializer):
    """POST body for adding one attendee: user_id XOR contact_id."""

    user_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(deleted_at__isnull=True), required=False, allow_null=True
    )
    contact_id = serializers.PrimaryKeyRelatedField(
        queryset=Contact.objects.all(), required=False, allow_null=True
    )
    is_required = serializers.BooleanField(default=True)

    def validate(self, attrs):
        user, contact = attrs.get("user_id"), attrs.get("contact_id")
        if bool(user) == bool(contact):  # both or neither
            raise serializers.ValidationError(
                {"detail": "Provide exactly one of user_id or contact_id."}
            )
        return attrs


class RescheduleSerializer(serializers.Serializer):
    scheduled_start = serializers.DateTimeField()
    scheduled_end = serializers.DateTimeField()

    def validate(self, attrs):
        if attrs["scheduled_end"] <= attrs["scheduled_start"]:
            raise serializers.ValidationError(
                {"scheduled_end": "The meeting must end after it starts."}
            )
        if attrs["scheduled_start"] <= timezone.now():
            raise serializers.ValidationError(
                {"scheduled_start": "Meetings are rescheduled to the future."}
            )
        return attrs


class CancelSerializer(serializers.Serializer):
    """A cancellation without a reason is a no-show with extra steps."""

    reason = serializers.CharField(max_length=255)


class RespondSerializer(serializers.Serializer):
    """RSVP body — PENDING is the absence of an answer, not an answer."""

    response = serializers.ChoiceField(
        choices=[
            MeetingAttendee.Response.ACCEPTED,
            MeetingAttendee.Response.DECLINED,
            MeetingAttendee.Response.TENTATIVE,
        ]
    )


class MinutesSerializer(serializers.ModelSerializer):
    recorded_by = UserSlimSerializer(read_only=True)

    class Meta:
        model = MeetingMinutes
        fields = ["id", "content", "recorded_by", "created_at", "updated_at"]


class MinutesWriteSerializer(serializers.Serializer):
    """PUT body — recorder comes from the JWT, meeting from the URL."""

    content = serializers.CharField()


class ActionItemSerializer(serializers.ModelSerializer):
    owner = UserSlimSerializer(read_only=True)
    owner_id = serializers.PrimaryKeyRelatedField(
        source="owner",
        queryset=User.objects.filter(deleted_at__isnull=True),
        required=False,
        allow_null=True,
        write_only=True,
    )

    class Meta:
        model = ActionItem
        fields = ["id", "description", "owner", "owner_id", "due_date", "is_done", "created_at"]
