from rest_framework import serializers

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    """
    Read-only by construction (the viewset is ReadOnlyModelViewSet, so no
    write path exists to validate). target_type renders the ContentType FK
    as "clients.client" — meaningful to an admin, unlike a bare CT id.
    """

    target_type = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "action",
            "actor",
            "actor_repr",
            "target_type",
            "object_id",
            "target_repr",
            "changes",
            "ip_address",
            "user_agent",
            "method",
            "path",
            "created_at",
        ]

    def get_target_type(self, obj):
        if obj.content_type is None:
            return None
        return f"{obj.content_type.app_label}.{obj.content_type.model}"
