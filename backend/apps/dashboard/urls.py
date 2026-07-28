"""No router: these are two plain GET views, not a resource with CRUD."""

from django.urls import path

from .views import DashboardChartsView, DashboardSummaryView

app_name = "dashboard"

urlpatterns = [
    path("dashboard/summary/", DashboardSummaryView.as_view(), name="summary"),
    path("dashboard/charts/", DashboardChartsView.as_view(), name="charts"),
]
