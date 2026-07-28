"""
Notification API. Everything here is scoped to request.user — there is no
role logic at all: notifications are personal mail, and even an ADMIN has
no business reading someone else's (queryset scoping per §8 layer 2:
out-of-scope rows 404, they don't 403).
"""

from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .filters import NotificationFilter
from .models import Notification, NotificationCategory, NotificationPreference, PushDevice
from .serializers import (
    NotificationPreferenceSerializer,
    NotificationSerializer,
    PushDeviceSerializer,
)


class NotificationViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """
    GET  /notifications/                     my notifications (paginated)
    GET  /notifications/?unread=true         badge dropdown
    GET  /notifications/unread-count/        the badge number
    POST /notifications/{id}/read/           mark one read (idempotent)
    POST /notifications/mark-all-read/       clear the badge
    """

    serializer_class = NotificationSerializer
    filterset_class = NotificationFilter

    def get_queryset(self):
        return (
            Notification.objects.filter(recipient=self.request.user)
            .select_related("actor", "content_type")  # serializer touches both — no N+1
            .order_by("-created_at")
        )

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        count = self.get_queryset().filter(read_at__isnull=True).count()
        return Response({"unread": count})

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        notification = self.get_object()
        if notification.read_at is None:  # idempotent: second click keeps the first timestamp
            notification.read_at = timezone.now()
            notification.save(update_fields=["read_at", "updated_at"])
        return Response(self.get_serializer(notification).data)

    @action(detail=False, methods=["post"], url_path="mark-all-read")
    def mark_all_read(self, request):
        updated = (
            self.get_queryset().filter(read_at__isnull=True).update(read_at=timezone.now())
        )  # one UPDATE, not N saves
        return Response({"marked_read": updated})


class NotificationPreferenceViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """
    GET   /notification-preferences/            full switchboard (one row per category)
    PATCH /notification-preferences/{category}/ flip switches for one category

    The URL key is the CATEGORY, not a numeric pk — the frontend renders a
    settings screen from the category list; ids would force it to first
    look them up. list() materializes missing rows so the client always
    sees the complete matrix, defaults included.
    """

    serializer_class = NotificationPreferenceSerializer
    lookup_field = "category"
    lookup_value_regex = "[a-z_]+"
    pagination_class = None  # a handful of rows; pagination is noise

    def get_queryset(self):
        return NotificationPreference.objects.filter(user=self.request.user)

    def list(self, request, *args, **kwargs):
        self._ensure_rows()
        return super().list(request, *args, **kwargs)

    def get_object(self):
        # PATCH on a category the user never touched must work too →
        # lazily create the row with defaults, then let DRF proceed.
        self._ensure_rows()
        return super().get_object()

    def _ensure_rows(self):
        existing = set(self.get_queryset().values_list("category", flat=True))
        missing = [
            NotificationPreference(user=self.request.user, category=cat)
            for cat in NotificationCategory.values
            if cat not in existing
        ]
        if missing:
            # ignore_conflicts: two concurrent first-visits race on the
            # unique constraint; losing the race is fine, the row exists.
            NotificationPreference.objects.bulk_create(missing, ignore_conflicts=True)


class PushDeviceViewSet(mixins.ListModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """
    GET    /push-devices/        my registered devices
    POST   /push-devices/        register (or re-claim) a token
    DELETE /push-devices/{id}/   unregister (e.g. on logout)
    """

    serializer_class = PushDeviceSerializer

    def get_queryset(self):
        return PushDevice.objects.filter(user=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Upsert on token: same browser re-registering is a refresh, and a
        # token that changed hands (new login on a shared machine) must be
        # RE-OWNED — pushing to the previous user would leak data.
        device, created = PushDevice.objects.update_or_create(
            token=serializer.validated_data["token"],
            defaults={
                "user": request.user,
                "platform": serializer.validated_data.get("platform", PushDevice.Platform.WEB),
            },
        )
        return Response(
            self.get_serializer(device).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
