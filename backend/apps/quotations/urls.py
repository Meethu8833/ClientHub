"""Routes: /api/v1/quotations/, /api/v1/quotation-items/."""

from rest_framework.routers import DefaultRouter

from .views import QuotationItemViewSet, QuotationViewSet

app_name = "quotations"

router = DefaultRouter()
router.register("quotations", QuotationViewSet, basename="quotation")
router.register("quotation-items", QuotationItemViewSet, basename="quotation-item")

urlpatterns = router.urls
