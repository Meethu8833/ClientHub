"""Routes: /api/v1/documents/ (+ /documents/{id}/download/)."""

from rest_framework.routers import DefaultRouter

from .views import DocumentViewSet

app_name = "documents"

router = DefaultRouter()
router.register("documents", DocumentViewSet, basename="document")

urlpatterns = router.urls
