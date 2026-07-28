"""No router: three plain GET endpoints, not a CRUD resource."""

from django.urls import path

from .views import RevenueReportView, TicketReportView, TimeReportView

app_name = "reports"

urlpatterns = [
    path("reports/revenue/", RevenueReportView.as_view(), name="revenue"),
    path("reports/time/", TimeReportView.as_view(), name="time"),
    path("reports/tickets/", TicketReportView.as_view(), name="tickets"),
]
