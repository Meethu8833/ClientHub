"""
Teams API (§6, §8).

Permission matrix applied here:
- ADMIN/MANAGER: full CRUD on departments, teams, seats; capacity reports.
- STAFF: read-only org structure; time off — their OWN rows only.

Nesting rule (§6): one level, read/create only; writes go flat.
    /departments/{id}/teams/     GET list + POST create
    /teams/{id}/members/         GET list + POST add seat
    /teams/{id}/capacity/        GET report (manager/admin)
    /team-memberships/{id}/      PATCH allocation / DELETE remove (manager/admin)
    /time-off/                   full CRUD (staff scoped to self)
"""

from datetime import date, timedelta

from django.db.models import Count, IntegerField, Q, Sum, Value
from django.db.models.functions import Coalesce
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, ValidationError
from rest_framework.response import Response

from apps.accounts.models import User
from apps.core.permissions import IsManagerOrAdmin, IsOwnerOrManager, ReadOnlyForStaff

from . import services
from .filters import TeamFilter, TeamMembershipFilter, TimeOffFilter
from .models import Department, Team, TeamMembership, TimeOff
from .serializers import (
    DepartmentDetailSerializer,
    DepartmentListSerializer,
    DepartmentWriteSerializer,
    TeamDetailSerializer,
    TeamListSerializer,
    TeamMembershipCreateSerializer,
    TeamMembershipSerializer,
    TeamMembershipUpdateSerializer,
    TeamWriteSerializer,
    TimeOffSerializer,
    TimeOffWriteSerializer,
)


def _annotated_teams(qs):
    """
    The computed columns every team read needs, in SQL (one query per page).
    Both aggregates traverse the SAME single join (memberships), so rows are
    not multiplied and Sum is safe — the multi-join Count trap needs at least
    two multivalued joins (contrast the project queryset).
    """
    return qs.select_related("department", "lead").annotate(
        member_count=Count("memberships", distinct=True),
        total_allocation=Coalesce(
            Sum("memberships__allocation_percent"), Value(0), output_field=IntegerField()
        ),
    )


def _parse_report_date(raw, param):
    """?from=/&to= are required ISO dates; anything else is a friendly 400."""
    if not raw:
        raise ValidationError({param: "This query parameter is required (YYYY-MM-DD)."})
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ValidationError({param: "Enter a valid date (YYYY-MM-DD)."}) from None


class DepartmentViewSet(viewsets.ModelViewSet):
    """
    GET    /departments/        list (?search= &ordering=)
    POST   /departments/        create              (manager/admin)
    GET    /departments/{id}/   detail (+ its live teams)
    PATCH  /departments/{id}/   update              (manager/admin)
    DELETE /departments/{id}/   SOFT delete — refused while live teams exist
    + nested /teams/ action
    """

    permission_classes = [ReadOnlyForStaff]
    search_fields = ["name", "description"]
    ordering_fields = ["name", "created_at"]
    ordering = ["name"]

    def get_queryset(self):
        # member_count = DISTINCT people across the department's live teams —
        # someone on two teams of one department is still one head.
        return (
            Department.objects.filter(is_active=True)
            .select_related("head")
            .annotate(
                team_count=Count("teams", filter=Q(teams__is_active=True), distinct=True),
                member_count=Count(
                    "teams__memberships__user",
                    filter=Q(teams__is_active=True),
                    distinct=True,
                ),
            )
        )

    def get_serializer_class(self):
        return {
            "list": DepartmentListSerializer,
            "create": DepartmentWriteSerializer,
            "partial_update": DepartmentWriteSerializer,
            "teams": TeamWriteSerializer,
        }.get(self.action, DepartmentDetailSerializer)

    def _detail_response(self, department, status_code=status.HTTP_200_OK):
        # Writes validate with the slim serializer but answer with the full
        # detail shape (annotated + teams), refreshing the frontend cache.
        department = self.get_queryset().prefetch_related("teams").get(pk=department.pk)
        data = DepartmentDetailSerializer(department, context=self.get_serializer_context()).data
        return Response(data, status=status_code)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._detail_response(serializer.save(), status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        # PATCH only (house rule): PUT invites accidental field-blanking.
        if not kwargs.get("partial"):
            raise MethodNotAllowed("PUT")
        super().update(request, *args, **kwargs)
        return self._detail_response(self.get_object())

    def destroy(self, request, *args, **kwargs):
        department = self.get_object()
        if department.teams.filter(is_active=True).exists():
            raise ValidationError(
                {"detail": "Disband or move this department's teams before deleting it."}
            )
        department.is_active = False
        department.save(update_fields=["is_active", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get", "post"])
    def teams(self, request, pk=None):
        """
        GET  /departments/{id}/teams/   the department's live teams
        POST /departments/{id}/teams/   create — parent from the URL (§6),
                                        manager/admin only (ReadOnlyForStaff)
        """
        department = self.get_object()  # 404s first for deleted ids

        if request.method == "GET":
            qs = _annotated_teams(department.teams.filter(is_active=True))
            page = self.paginate_queryset(qs)
            return self.get_paginated_response(TeamListSerializer(page, many=True).data)

        context = {**self.get_serializer_context(), "department": department}
        serializer = TeamWriteSerializer(data=request.data, context=context)
        serializer.is_valid(raise_exception=True)
        team = serializer.save()
        team = _annotated_teams(Team.objects.filter(pk=team.pk)).get()
        data = TeamDetailSerializer(team, context=self.get_serializer_context()).data
        return Response(data, status=status.HTTP_201_CREATED)


class TeamViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    Flat team resource (create stays nested under the department, §6).

    GET    /teams/?department=2&member=7&search=
    GET    /teams/{id}/          detail (all seats + allocations)
    PATCH  /teams/{id}/          name/description/lead (manager/admin)
    DELETE /teams/{id}/          SOFT delete — frees members' allocation share
    GET|POST /teams/{id}/members/    seats (POST manager/admin)
    GET    /teams/{id}/capacity/?from=&to=   report (manager/admin)
    """

    permission_classes = [ReadOnlyForStaff]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filterset_class = TeamFilter
    search_fields = ["name", "description"]
    ordering_fields = ["name", "created_at"]
    ordering = ["name"]

    def get_queryset(self):
        qs = _annotated_teams(Team.objects.filter(is_active=True))
        if self.action == "retrieve":
            qs = qs.prefetch_related("memberships__user", "memberships__team")
        return qs

    def get_serializer_class(self):
        return {
            "list": TeamListSerializer,
            "partial_update": TeamWriteSerializer,
            "members": TeamMembershipCreateSerializer,
        }.get(self.action, TeamDetailSerializer)

    def _detail_response(self, team, status_code=status.HTTP_200_OK):
        team = (
            self.get_queryset()
            .prefetch_related("memberships__user", "memberships__team")
            .get(pk=team.pk)
        )
        data = TeamDetailSerializer(team, context=self.get_serializer_context()).data
        return Response(data, status=status_code)

    def update(self, request, *args, **kwargs):
        if not kwargs.get("partial"):
            raise MethodNotAllowed("PUT")
        super().update(request, *args, **kwargs)
        return self._detail_response(self.get_object())

    def destroy(self, request, *args, **kwargs):
        team = self.get_object()
        team.is_active = False
        team.save(update_fields=["is_active", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get", "post"])
    def members(self, request, pk=None):
        team = self.get_object()

        if request.method == "GET":
            qs = team.memberships.select_related("user", "team")
            page = self.paginate_queryset(qs)
            return self.get_paginated_response(TeamMembershipSerializer(page, many=True).data)

        context = {**self.get_serializer_context(), "team": team}
        serializer = TeamMembershipCreateSerializer(data=request.data, context=context)
        serializer.is_valid(raise_exception=True)
        membership = serializer.save()
        return Response(TeamMembershipSerializer(membership).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], permission_classes=[IsManagerOrAdmin])
    def capacity(self, request, pk=None):
        """
        GET /teams/{id}/capacity/?from=2026-08-03&to=2026-08-28 — the planning
        report: per member gross/net capacity hours, absence days, logged
        hours and utilization. Management information → manager/admin only,
        same reasoning as hiding project budgets from staff.
        """
        team = self.get_object()
        start = _parse_report_date(request.query_params.get("from"), "from")
        end = _parse_report_date(request.query_params.get("to"), "to")
        if end < start:
            raise ValidationError({"to": "End of the window cannot be before its start."})
        if end - start > timedelta(days=services.MAX_REPORT_DAYS):
            raise ValidationError({"to": "Report window is limited to one year."})
        return Response(services.team_capacity_report(team=team, start=start, end=end))


class TeamMembershipViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    Flat seat resource (manager/admin — "manage members" §8):
    GET   /team-memberships/?user=7   one person's allocations everywhere
    PATCH /team-memberships/{id}/     {allocation_percent}
    DELETE                            remove from the team
    """

    permission_classes = [IsManagerOrAdmin]
    http_method_names = ["get", "patch", "delete", "head", "options"]
    filterset_class = TeamMembershipFilter
    ordering_fields = ["allocation_percent", "created_at"]
    ordering = ["-allocation_percent", "created_at"]

    def get_queryset(self):
        return TeamMembership.objects.filter(team__is_active=True).select_related(
            "user", "team", "team__department"
        )

    def get_serializer_class(self):
        return (
            TeamMembershipUpdateSerializer
            if self.action == "partial_update"
            else TeamMembershipSerializer
        )

    def update(self, request, *args, **kwargs):
        if not kwargs.get("partial"):
            raise MethodNotAllowed("PUT")
        super().update(request, *args, **kwargs)
        return Response(TeamMembershipSerializer(self.get_object()).data)


class TimeOffViewSet(viewsets.ModelViewSet):
    """
    Availability ledger.
    GET    /time-off/?user=&type=&from_date=&to_date=   calendar (staff: own rows)
    POST   /time-off/          record an absence (staff: self only)
    PATCH  /time-off/{id}/     fix a row   (owner or manager/admin)
    DELETE /time-off/{id}/     cancel      (owner or manager/admin)

    Staff querysets are scoped to their own rows (§8): list, detail, update
    and delete stay consistent, and other people's ids 404 — colleagues'
    absence reasons are between them and their manager.
    """

    owner_field = "user"  # read by IsOwnerOrManager
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filterset_class = TimeOffFilter
    ordering_fields = ["start_date", "created_at"]
    ordering = ["-start_date", "-id"]

    def get_permissions(self):
        perms = super().get_permissions()  # IsAuthenticated (settings default)
        if self.action in ("partial_update", "destroy"):
            perms.append(IsOwnerOrManager())
        return perms

    def get_queryset(self):
        qs = TimeOff.objects.select_related("user")
        if self.request.user.role == User.Role.STAFF:
            qs = qs.filter(user=self.request.user)
        return qs

    def get_serializer_class(self):
        if self.action in ("create", "partial_update"):
            return TimeOffWriteSerializer
        return TimeOffSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entry = serializer.save()
        return Response(TimeOffSerializer(entry).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        if not kwargs.get("partial"):
            raise MethodNotAllowed("PUT")
        super().update(request, *args, **kwargs)
        return Response(TimeOffSerializer(self.get_object()).data)
