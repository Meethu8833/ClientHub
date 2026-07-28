"""
GET /api/v1/audit-logs/        list, filterable
GET /api/v1/audit-logs/{id}/   one entry

ReadOnlyModelViewSet: the router only wires list+retrieve, so POST/PUT/
PATCH/DELETE answer 405 — the append-only guarantee enforced by routing,
not by convention. Admin-only: the log exposes IPs, emails of failed
logins, and raw field diffs across every client — far more than any
non-admin role is entitled to see.
"""

from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.core.permissions import IsAdmin

from .models import AuditLog
from .serializers import AuditLogSerializer


class AuditLogViewSet(ReadOnlyModelViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [IsAdmin]
    # select_related: the list joins actor + content_type in one query
    # instead of 2 extra queries per row (the classic N+1).
    queryset = AuditLog.objects.select_related("actor", "content_type")

    # ?action=login_failed&created_at__gte=2026-07-01  /  ?actor=3
    # ?content_type=12&object_id=7 — full history of one record.
    filterset_fields = {
        "action": ["exact"],
        "actor": ["exact"],
        "content_type": ["exact"],
        "object_id": ["exact"],
        "created_at": ["gte", "lte"],
    }
    search_fields = ["actor_repr", "target_repr"]
    ordering_fields = ["created_at"]
