"""
Serializers. Notifications are READ-ONLY over the API — the server writes
them (via services.notify), clients only list them and flip read state
through dedicated actions. The only client-writable things here are the
preference switches and push-device registration.
"""

from rest_framework import serializers

from .models import Notification, NotificationPreference, PushDevice


class ActorSerializer(serializers.Serializer):
    """Tiny embedded shape — enough for '<avatar> Maria assigned…' UI."""

    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(source="get_full_name", read_only=True)


class NotificationSerializer(serializers.ModelSerializer):
    actor = ActorSerializer(read_only=True)
    is_read = serializers.BooleanField(read_only=True)
    # GenericFK flattened for the frontend router: ("tickets.ticket", 42)
    # is everything it needs to build the deep-link URL.
    target_type = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id",
            "category",
            "title",
            "body",
            "actor",
            "target_type",
            "object_id",
            "is_read",
            "read_at",
            "created_at",
        ]
        read_only_fields = fields  # nothing is client-writable

    def get_target_type(self, obj) -> str | None:
        if obj.content_type_id is None:
            return None
        return f"{obj.content_type.app_label}.{obj.content_type.model}"


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = ["category", "in_app_enabled", "email_enabled", "push_enabled"]
        # The category is the URL lookup key, never changed via the body —
        # renaming a row's category would silently move the switches.
        read_only_fields = ["category"]


class PushDeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PushDevice
        fields = ["id", "token", "platform", "created_at"]
        read_only_fields = ["id", "created_at"]
        # The model's unique=True on token would make DRF reject
        # re-registration with 400; we WANT re-registration to upsert
        # (view handles it), so drop the auto-generated validator.
        extra_kwargs = {"token": {"validators": []}}
