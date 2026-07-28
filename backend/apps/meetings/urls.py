"""Routes: /api/v1/meetings/, /api/v1/meeting-attendees/, /api/v1/action-items/."""

from rest_framework.routers import DefaultRouter

from .views import ActionItemViewSet, MeetingAttendeeViewSet, MeetingViewSet

app_name = "meetings"

router = DefaultRouter()
router.register("meetings", MeetingViewSet, basename="meeting")
router.register("meeting-attendees", MeetingAttendeeViewSet, basename="meeting-attendee")
router.register("action-items", ActionItemViewSet, basename="action-item")

urlpatterns = router.urls
