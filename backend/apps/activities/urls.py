"""Routes: /api/v1/notes/ and the read-only /api/v1/activities/ timeline."""

from rest_framework.routers import DefaultRouter

from .views import ActivityViewSet, NoteViewSet

app_name = "activities"

router = DefaultRouter()
router.register("notes", NoteViewSet, basename="note")
router.register("activities", ActivityViewSet, basename="activity")

urlpatterns = router.urls
