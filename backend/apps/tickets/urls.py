"""Routes: /api/v1/tickets/, /api/v1/ticket-categories/, /api/v1/sla-policies/."""

from rest_framework.routers import DefaultRouter

from .views import SlaPolicyViewSet, TicketCategoryViewSet, TicketViewSet

app_name = "tickets"

router = DefaultRouter()
router.register("tickets", TicketViewSet, basename="ticket")
router.register("ticket-categories", TicketCategoryViewSet, basename="ticket-category")
router.register("sla-policies", SlaPolicyViewSet, basename="sla-policy")

urlpatterns = router.urls
