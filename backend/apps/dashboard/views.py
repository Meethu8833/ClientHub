"""
Dashboard API (docs/dashboard-module.md):

    /dashboard/summary/   GET  KPI tiles for the home screen
    /dashboard/charts/    GET  chart datasets (time series + distributions)

Plain APIViews, not ViewSets: there is no model, no queryset, no pagination —
a ViewSet's machinery would all be dead weight. No serializer either: the
payload is computed aggregates, not model instances; its shape is documented
in extend_schema and pinned by tests.

Caching (the whole point of this file): dashboards are read on every page
load, are expensive (7+ aggregate queries), and tolerate staleness — nobody
acts on a KPI tile that is 2 minutes old. So: low-level cache API, short TTL,
no invalidation. Two subtleties carry all the security:

  * the key must include EVERYTHING that changes the payload — here, the
    scope. Admin/manager see identical global data → one shared key ("scope
    is global" is the fact, the role is not). STAFF data is per-user → per-
    user keys. Getting this wrong serves one user's numbers to another.
  * "v1" in the key: when a deploy changes the payload shape, bump it and
    stale entries are simply never read again — no cache flush ceremony.
"""

from django.core.cache import cache
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User

from . import services

CACHE_TTL_SECONDS = 120


def _cache_key(kind: str, user) -> str:
    if user.role == User.Role.STAFF:
        return f"dashboard:{kind}:v1:user:{user.id}"
    return f"dashboard:{kind}:v1:global"


class _CachedDashboardView(APIView):
    permission_classes = [IsAuthenticated]
    kind = ""  # subclasses set; doubles as the cache-key segment

    def build(self, user) -> dict:  # pragma: no cover — overridden
        raise NotImplementedError

    def get(self, request):
        key = _cache_key(self.kind, request.user)
        data = cache.get(key)
        if data is None:
            data = self.build(request.user)
            cache.set(key, data, CACHE_TTL_SECONDS)
        return Response(data)


@extend_schema(
    summary="Dashboard KPI summary",
    description=(
        "Aggregated counts for the home screen, scoped to the caller's role. "
        "STAFF see member-projects/own-quotations numbers and NO billing "
        "block. Cached for 2 minutes; `as_of` is the computation time."
    ),
    responses={200: OpenApiResponse(description="KPI blocks keyed by domain")},
)
class DashboardSummaryView(_CachedDashboardView):
    kind = "summary"

    def build(self, user):
        return services.get_summary(user)


@extend_schema(
    summary="Dashboard chart datasets",
    description=(
        "Zero-filled time series (revenue, tickets) and distributions "
        "(project status, invoice aging), ready to plot. Revenue and aging "
        "appear for manager/admin only. Cached for 2 minutes."
    ),
    responses={200: OpenApiResponse(description="Chart datasets keyed by name")},
)
class DashboardChartsView(_CachedDashboardView):
    kind = "charts"

    def build(self, user):
        return services.get_charts(user)
