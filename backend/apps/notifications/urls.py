"""Routes: /api/v1/notifications/, /notification-preferences/, /push-devices/."""

from rest_framework.routers import DefaultRouter

from .views import NotificationPreferenceViewSet, NotificationViewSet, PushDeviceViewSet

app_name = "notifications"

router = DefaultRouter()
router.register("notifications", NotificationViewSet, basename="notification")
router.register(
    "notification-preferences", NotificationPreferenceViewSet, basename="notification-preference"
)
router.register("push-devices", PushDeviceViewSet, basename="push-device")

urlpatterns = router.urls
