"""Routes: /api/v1/invoices/, /api/v1/invoice-items/, /api/v1/payments/,
/api/v1/refunds/."""

from rest_framework.routers import DefaultRouter

from .views import InvoiceItemViewSet, InvoiceViewSet, PaymentViewSet, RefundViewSet

app_name = "billing"

router = DefaultRouter()
router.register("invoices", InvoiceViewSet, basename="invoice")
router.register("invoice-items", InvoiceItemViewSet, basename="invoice-item")
router.register("payments", PaymentViewSet, basename="payment")
router.register("refunds", RefundViewSet, basename="refund")

urlpatterns = router.urls
