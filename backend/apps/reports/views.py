"""
Report API (docs/reports-module.md):

    /reports/revenue/  GET  manager/admin   invoiced/collected/refunded/net
    /reports/time/     GET  all roles       logged hours (STAFF: own only)
    /reports/tickets/  GET  all roles       SLA performance per priority

One GET each, three response formats via ?export=json|xlsx|pdf. Plain
APIViews for the same reason as the dashboard: no model, no queryset —
ViewSet machinery would be dead weight. NOT ?format= : DRF reserves that
query param for its own content negotiation (json/api renderers), and
hijacking it breaks the browsable API in surprising ways.

No caching, deliberately: dashboards are hit on every page load, reports a
few times a day with arbitrary filter combinations — a cache would mostly
store keys nobody reads twice, and a stale export that gets emailed onward
is worse than a slow one.
"""

from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsManagerOrAdmin

from . import exporters, serializers, services

# Documented once, shared by every report's schema entry.
_COMMON_PARAMS = [
    OpenApiParameter("date_from", str, description="YYYY-MM-DD, default: 365 days ago"),
    OpenApiParameter("date_to", str, description="YYYY-MM-DD, default: today"),
    OpenApiParameter("export", str, enum=["json", "xlsx", "pdf"], description="Response format"),
]


class BaseReportView(APIView):
    """
    Template-method base: subclasses say WHICH params and HOW to build;
    this class owns the invariant pipeline —

        validate query params → build ReportTable → render json/xlsx/pdf
    """

    permission_classes = [IsAuthenticated]
    params_class: type[serializers.BaseReportParams]
    slug = ""  # filename stem: "revenue-report-2026-07-28.xlsx"

    def build(self, user, params) -> services.ReportTable:  # pragma: no cover
        raise NotImplementedError

    def get(self, request):
        params = self.params_class(data=request.query_params)
        params.is_valid(raise_exception=True)  # bad input → 400, view body never runs
        data = params.validated_data
        export = data.pop("export")

        table = self.build(request.user, data)

        filename = f"{self.slug}-{timezone.localdate().isoformat()}.{export}"
        if export == serializers.EXPORT_XLSX:
            return exporters.xlsx_response(table, filename)
        if export == serializers.EXPORT_PDF:
            return exporters.pdf_response(table, filename)
        return Response(table.as_dict())


@extend_schema(
    summary="Revenue report",
    description=(
        "Invoiced / collected / refunded / net per month or per client. "
        "Manager and admin only — STAFF have no billing visibility (§8)."
    ),
    parameters=_COMMON_PARAMS
    + [
        OpenApiParameter("client", int, description="Limit to one client"),
        OpenApiParameter("group_by", str, enum=["month", "client"]),
    ],
    responses={200: OpenApiResponse(description="ReportTable JSON, or an xlsx/pdf attachment")},
)
class RevenueReportView(BaseReportView):
    permission_classes = [IsManagerOrAdmin]
    params_class = serializers.RevenueReportParams
    slug = "revenue-report"

    def build(self, user, params):
        return services.revenue_report(params)


@extend_schema(
    summary="Time tracking report",
    description=(
        "Logged hours by project or by team member. STAFF see only their "
        "own entries regardless of filters."
    ),
    parameters=_COMMON_PARAMS
    + [
        OpenApiParameter("project", int, description="Limit to one project"),
        OpenApiParameter("user", int, description="Limit to one member (manager/admin only)"),
        OpenApiParameter("group_by", str, enum=["project", "user"]),
    ],
    responses={200: OpenApiResponse(description="ReportTable JSON, or an xlsx/pdf attachment")},
)
class TimeReportView(BaseReportView):
    params_class = serializers.TimeReportParams
    slug = "time-report"

    def build(self, user, params):
        return services.time_report(user, params)


@extend_schema(
    summary="Ticket SLA report",
    description=(
        "Per-priority ticket volume, SLA breaches and average resolution "
        "time for tickets created in the window. Shared queue — all roles."
    ),
    parameters=_COMMON_PARAMS
    + [OpenApiParameter("client", int, description="Limit to one client")],
    responses={200: OpenApiResponse(description="ReportTable JSON, or an xlsx/pdf attachment")},
)
class TicketReportView(BaseReportView):
    params_class = serializers.TicketReportParams
    slug = "ticket-sla-report"

    def build(self, user, params):
        return services.ticket_report(params)
