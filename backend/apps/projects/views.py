"""
Projects API (ARCHITECTURE.md §6, §8 — Phase 4, first slice).

Permission matrix applied here:
- ADMIN/MANAGER: full CRUD on projects, members, milestones; see everything.
- STAFF: read-only, and only projects they are MEMBERS of (queryset scoping —
  out-of-scope ids 404, existence never leaks).

Nesting rule (§6): one level, read/create only; writes go flat.
    /projects/{id}/members/       GET list + POST add
    /projects/{id}/milestones/    GET list + POST create
    /projects/{id}/tasks/         GET list + POST create
    /project-memberships/{id}/    PATCH role / DELETE remove   (manager/admin)
    /milestones/{id}/             GET/PATCH/DELETE             (flat)
    /tasks/{id}/                  GET/PATCH/DELETE (flat; staff: own status only)
    /tasks/{id}/time-entries/     GET list + POST log hours
    /time-entries/{id}/           PATCH/DELETE (owner or manager/admin)
    /technologies/                GET all roles, POST manager/admin
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, IntegerField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.accounts.models import User
from apps.core.permissions import IsManagerOrAdmin, IsOwnerOrManager, ReadOnlyForStaff

from . import services
from .filters import MilestoneFilter, ProjectFilter, SprintFilter, TaskFilter, TimeEntryFilter
from .models import Milestone, Project, ProjectMembership, Sprint, Task, Technology, TimeEntry
from .serializers import (
    MembershipCreateSerializer,
    MembershipSerializer,
    MembershipUpdateSerializer,
    MilestoneSerializer,
    MilestoneWriteSerializer,
    ProjectDetailSerializer,
    ProjectListSerializer,
    ProjectWriteSerializer,
    SprintSerializer,
    SprintWriteSerializer,
    TaskDetailSerializer,
    TaskListSerializer,
    TaskWriteSerializer,
    TechnologySerializer,
    TimeEntrySerializer,
    TimeEntryWriteSerializer,
)


def _scope_to_member(qs, user, prefix=""):
    """
    Layer-2 scoping (§8): STAFF see only projects they belong to. Applied to
    every queryset that hangs off a project (`prefix` walks the FK path).
    """
    if user.role == User.Role.STAFF:
        qs = qs.filter(**{f"{prefix}memberships__user": user})
    return qs


def _annotated_tasks(qs):
    """
    The computed columns every task read needs, in SQL (one query per page):

    - logged_hours via SUBQUERY, not Sum through the join: this queryset also
      joins blocked_by (open_blockers) and possibly memberships (scoping), and
      Sum has no distinct= escape hatch — joined duplicates would inflate the
      total (the same multi-annotation trap as the project Counts, but where
      distinct=True cannot save you).
    - open_blockers: Count(distinct) is safe for counting ids.
    """
    logged = (
        TimeEntry.objects.filter(task=OuterRef("pk"))
        .values("task")  # GROUP BY task → the subquery returns exactly one row
        .annotate(total=Sum("hours"))
        .values("total")
    )
    return qs.select_related("project", "milestone", "assignee").annotate(
        logged_hours=Coalesce(
            Subquery(logged),
            Value(Decimal("0")),
            output_field=DecimalField(max_digits=8, decimal_places=2),
        ),
        open_blockers=Count(
            "blocked_by", filter=~Q(blocked_by__status=Task.Status.DONE), distinct=True
        ),
    )


def _annotated_sprints(qs):
    """
    Live sprint numbers in SQL: how many tasks, how many points. One
    multivalued join (tasks), so Sum is safe here — no Subquery gymnastics
    needed (contrast _annotated_tasks, which joins twice).
    """
    return qs.select_related("project").annotate(
        task_count=Count("tasks", distinct=True),
        points_committed=Coalesce(
            Sum("tasks__story_points"), Value(0), output_field=IntegerField()
        ),
    )


class ProjectViewSet(viewsets.ModelViewSet):
    """
    GET    /projects/        list (?search= &status= &priority= &member= …)
    POST   /projects/        create              (manager/admin)
    GET    /projects/{id}/   detail (team + milestones + progress)
    PATCH  /projects/{id}/   update              (manager/admin)
    DELETE /projects/{id}/   SOFT delete         (manager/admin)
    + nested members / milestones actions
    """

    permission_classes = [ReadOnlyForStaff]
    filterset_class = ProjectFilter
    search_fields = ["name", "description", "client__name", "technologies__name"]
    # No budget in the ordering whitelist: staff could binary-search hidden
    # values through sort order even though the field itself is stripped.
    ordering_fields = ["name", "status", "priority", "start_date", "end_date", "created_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        # distinct=True on every Count: the multiple JOINs (memberships,
        # milestones) multiply each other's rows, so a plain COUNT would
        # return members × milestones. Classic multi-annotation trap.
        qs = (
            Project.objects.filter(is_active=True)
            .select_related("client")
            .prefetch_related("technologies")
            .annotate(
                member_count=Count("memberships", distinct=True),
                milestone_total=Count("milestones", distinct=True),
                milestone_done=Count(
                    "milestones", filter=Q(milestones__is_completed=True), distinct=True
                ),
            )
        )
        qs = _scope_to_member(qs, self.request.user)
        if self.action == "retrieve":
            qs = qs.prefetch_related("memberships__user", "milestones")
        return qs

    def get_serializer_class(self):
        return {
            "list": ProjectListSerializer,
            "create": ProjectWriteSerializer,
            "partial_update": ProjectWriteSerializer,
            "members": MembershipCreateSerializer,
            "milestones": MilestoneWriteSerializer,
            "tasks": TaskWriteSerializer,
            "sprints": SprintWriteSerializer,
        }.get(self.action, ProjectDetailSerializer)

    def _detail_response(self, project, status_code=status.HTTP_200_OK):
        # Writes validate with the slim serializer but answer with the full
        # detail shape (annotated + prefetched), refreshing the frontend cache.
        project = (
            self.get_queryset()
            .prefetch_related("memberships__user", "milestones")
            .get(pk=project.pk)
        )
        data = ProjectDetailSerializer(project, context=self.get_serializer_context()).data
        return Response(data, status=status_code)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        project = serializer.save()
        return self._detail_response(project, status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        # PATCH only (house rule): PUT invites accidental field-blanking.
        if not kwargs.get("partial"):
            raise MethodNotAllowed("PUT")
        super().update(request, *args, **kwargs)
        return self._detail_response(self.get_object())

    def destroy(self, request, *args, **kwargs):
        services.soft_delete_project(project=self.get_object(), actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get", "post"])
    def members(self, request, pk=None):
        project = self.get_object()  # 404s first for out-of-scope/deleted ids

        if request.method == "GET":
            qs = project.memberships.select_related("user")
            page = self.paginate_queryset(qs)
            return self.get_paginated_response(MembershipSerializer(page, many=True).data)

        context = {**self.get_serializer_context(), "project": project}
        serializer = MembershipCreateSerializer(data=request.data, context=context)
        serializer.is_valid(raise_exception=True)
        membership = serializer.save()
        return Response(MembershipSerializer(membership).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "post"])
    def milestones(self, request, pk=None):
        project = self.get_object()

        if request.method == "GET":
            qs = project.milestones.all()
            page = self.paginate_queryset(qs)
            return self.get_paginated_response(MilestoneSerializer(page, many=True).data)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        milestone = serializer.save(project=project)  # parent from the URL, not the body
        return Response(MilestoneSerializer(milestone).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "post"])
    def tasks(self, request, pk=None):
        """
        GET  /projects/{id}/tasks/   the project's task list (unfiltered;
                                     the kanban uses flat /tasks/?project=)
        POST /projects/{id}/tasks/   create — parent from the URL (§6),
                                     manager/admin only (ReadOnlyForStaff)
        """
        project = self.get_object()

        if request.method == "GET":
            qs = _annotated_tasks(project.tasks.all())
            page = self.paginate_queryset(qs)
            data = TaskListSerializer(page, many=True, context=self.get_serializer_context()).data
            return self.get_paginated_response(data)

        context = {**self.get_serializer_context(), "project": project}
        serializer = TaskWriteSerializer(data=request.data, context=context)
        serializer.is_valid(raise_exception=True)
        task = serializer.save(project=project)
        # Answer with the full detail shape (annotated + both dependency sides).
        task = (
            _annotated_tasks(Task.objects.filter(pk=task.pk))
            .prefetch_related("blocked_by", "blocks")
            .get()
        )
        data = TaskDetailSerializer(task, context=self.get_serializer_context()).data
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "post"])
    def sprints(self, request, pk=None):
        """
        GET  /projects/{id}/sprints/   the project's sprint list (newest first)
        POST /projects/{id}/sprints/   create a PLANNED sprint — parent from
                                       the URL (§6), manager/admin only
        """
        project = self.get_object()

        if request.method == "GET":
            qs = _annotated_sprints(project.sprints.all())
            page = self.paginate_queryset(qs)
            return self.get_paginated_response(SprintSerializer(page, many=True).data)

        context = {**self.get_serializer_context(), "project": project}
        serializer = SprintWriteSerializer(data=request.data, context=context)
        serializer.is_valid(raise_exception=True)
        sprint = serializer.save(project=project)  # parent from the URL, not the body
        sprint = _annotated_sprints(Sprint.objects.filter(pk=sprint.pk)).get()
        return Response(SprintSerializer(sprint).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def velocity(self, request, pk=None):
        """
        GET /projects/{id}/velocity/ — the velocity report: every completed
        sprint's snapshot numbers (chronological, chart-ready) plus the
        average of the LAST 5 — the number used to plan the next sprint.
        Reads only the frozen snapshots; live rows never distort history.
        """
        project = self.get_object()
        completed = list(
            project.sprints.filter(status=Sprint.Status.COMPLETED)
            .order_by("completed_at")
            .values("id", "name", "completed_points", "total_points")
        )
        recent = completed[-5:]
        velocity = (
            round(sum(s["completed_points"] or 0 for s in recent) / len(recent), 1)
            if recent
            else None
        )
        return Response({"velocity": velocity, "sprints": completed})


class ProjectMembershipViewSet(
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    Flat writes for team rows (manager/admin only — "manage members" in §8):
    PATCH /project-memberships/{id}/ {role} · DELETE removes from the team.
    """

    permission_classes = [IsManagerOrAdmin]
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return ProjectMembership.objects.filter(project__is_active=True).select_related(
            "user", "project"
        )

    def get_serializer_class(self):
        return (
            MembershipUpdateSerializer if self.action == "partial_update" else MembershipSerializer
        )

    def update(self, request, *args, **kwargs):
        membership = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            membership = services.change_member_role(
                membership=membership, role=serializer.validated_data["role"], actor=request.user
            )
        except services.LastManagerError as e:
            raise ValidationError({"role": str(e)}) from e
        return Response(MembershipSerializer(membership).data)

    def destroy(self, request, *args, **kwargs):
        try:
            services.remove_member(membership=self.get_object(), actor=request.user)
        except services.LastManagerError as e:
            raise ValidationError({"detail": str(e)}) from e
        return Response(status=status.HTTP_204_NO_CONTENT)


class MilestoneViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    Flat milestone resource. The cross-project list powers the deadlines
    screen: GET /milestones/?is_completed=false&due_before=2026-08-03.
    Create stays nested under the project (§6).
    """

    permission_classes = [ReadOnlyForStaff]
    http_method_names = ["get", "patch", "delete", "head", "options"]
    filterset_class = MilestoneFilter
    ordering_fields = ["due_date", "created_at"]
    ordering = ["due_date"]

    def get_queryset(self):
        qs = Milestone.objects.filter(project__is_active=True).select_related("project")
        return _scope_to_member(qs, self.request.user, prefix="project__")

    def get_serializer_class(self):
        return MilestoneWriteSerializer if self.action == "partial_update" else MilestoneSerializer

    def update(self, request, *args, **kwargs):
        super().update(request, *args, **kwargs)
        return Response(MilestoneSerializer(self.get_object()).data)


class SprintViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    Flat sprint resource (create stays nested under the project, §6).

    GET    /sprints/?project=3&status=active   boards, reports
    GET    /sprints/{id}/                      detail (live + snapshot numbers)
    PATCH  /sprints/{id}/                      name/goal/dates (not COMPLETED ones)
    DELETE /sprints/{id}/                      PLANNED only — active/completed
                                               sprints are velocity history
    POST   /sprints/{id}/start/                ceremony: PLANNED → ACTIVE
    POST   /sprints/{id}/complete/             ceremony: ACTIVE → COMPLETED
    GET    /sprints/{id}/burndown/             chart data (remaining vs ideal)

    ReadOnlyForStaff covers the whole matrix: the ceremonies are POSTs, so
    staff get 403 on them and full read access to boards/burndowns.
    """

    permission_classes = [ReadOnlyForStaff]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filterset_class = SprintFilter
    ordering_fields = ["start_date", "end_date", "created_at", "name"]
    ordering = ["-start_date", "-id"]

    def get_queryset(self):
        qs = Sprint.objects.filter(project__is_active=True)
        qs = _scope_to_member(qs, self.request.user, prefix="project__")
        return _annotated_sprints(qs)

    def get_serializer_class(self):
        return SprintWriteSerializer if self.action == "partial_update" else SprintSerializer

    def _detail_response(self, sprint, status_code=status.HTTP_200_OK):
        sprint = self.get_queryset().get(pk=sprint.pk)  # re-read with annotations
        return Response(SprintSerializer(sprint).data, status=status_code)

    def update(self, request, *args, **kwargs):
        super().update(request, *args, **kwargs)
        return self._detail_response(self.get_object())

    def destroy(self, request, *args, **kwargs):
        sprint = self.get_object()
        if sprint.status != Sprint.Status.PLANNED:
            raise ValidationError(
                {"detail": "Only planned sprints can be deleted — history must survive."}
            )
        # FK is SET_NULL: any tasks already pulled in fall back to the backlog.
        sprint.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        try:
            sprint = services.start_sprint(sprint=self.get_object(), actor=request.user)
        except services.SprintStateError as e:
            raise ValidationError({"detail": str(e)}) from e
        return self._detail_response(sprint)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        try:
            sprint = services.complete_sprint(sprint=self.get_object(), actor=request.user)
        except services.SprintStateError as e:
            raise ValidationError({"detail": str(e)}) from e
        return self._detail_response(sprint)

    @action(detail=True, methods=["get"])
    def burndown(self, request, pk=None):
        """
        One row per calendar day of the timebox:
          {date, ideal, remaining}
        ideal     — the straight line from total_points down to 0;
        remaining — total minus points of tasks DONE by end of that day
                    (from Task.completed_at); null for days still in the
                    future, so the chart's actual line stops at today.
        """
        sprint = self.get_object()
        if sprint.status == Sprint.Status.PLANNED:
            raise ValidationError({"detail": "Burndown is available once the sprint starts."})

        # Completed sprints read the frozen snapshot (unfinished tasks left
        # for the backlog at completion — a live Sum would under-count).
        if sprint.status == Sprint.Status.COMPLETED:
            total = sprint.total_points or 0
        else:
            total = sprint.tasks.aggregate(s=Sum("story_points"))["s"] or 0

        done = [
            (timezone.localtime(finished).date(), points or 0)
            for finished, points in sprint.tasks.filter(
                status=Task.Status.DONE, completed_at__isnull=False
            ).values_list("completed_at", "story_points")
        ]

        span = (sprint.end_date - sprint.start_date).days  # ≥ 0 by DB constraint
        today = timezone.localdate()
        days = []
        for offset in range(span + 1):
            day = sprint.start_date + timedelta(days=offset)
            burned = sum(points for finished, points in done if finished <= day)
            days.append(
                {
                    "date": day,
                    "ideal": round(total * (span - offset) / span, 2) if span else 0,
                    "remaining": max(total - burned, 0) if day <= today else None,
                }
            )
        return Response(
            {
                "sprint": sprint.pk,
                "start_date": sprint.start_date,
                "end_date": sprint.end_date,
                "total_points": total,
                "days": days,
            }
        )


class TaskViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    Flat task resource (§6: nested create lives under /projects/{id}/tasks/).

    GET    /tasks/?project=3&status=todo…   kanban columns, "my tasks" screens
    GET    /tasks/{id}/                     detail (dependencies, hours)
    PATCH  /tasks/{id}/                     manager/admin: any field;
                                            STAFF: status only, own tasks only (§8)
    DELETE /tasks/{id}/                     manager/admin (goes through the
                                            service — cleans GenericFK orphans)
    + /tasks/{id}/time-entries/             nested GET list + POST log hours

    Permission shape is unusual on purpose: ReadOnlyForStaff would 403 every
    staff PATCH, but the matrix grants staff ONE write — moving their own card
    on the board — so writes are arbitrated inside update() instead.
    """

    # "post" is for the time-entries action only — flat POST /tasks/ still
    # 405s because there is no CreateModelMixin (create is nested, §6).
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filterset_class = TaskFilter
    search_fields = ["title", "description"]
    # priority/status sort alphabetically (their stored strings), which is NOT
    # semantic order — the board sorts columns client-side; these cover tables.
    ordering_fields = ["due_date", "priority", "status", "created_at", "title"]
    ordering = ["-created_at"]

    def get_permissions(self):
        if self.action == "destroy":
            return [IsManagerOrAdmin()]
        return super().get_permissions()  # IsAuthenticated (settings default)

    def get_queryset(self):
        qs = Task.objects.filter(project__is_active=True)
        qs = _scope_to_member(qs, self.request.user, prefix="project__")
        qs = _annotated_tasks(qs)
        if self.action == "retrieve":
            qs = qs.prefetch_related("blocked_by", "blocks")
        return qs

    def get_serializer_class(self):
        return {
            "list": TaskListSerializer,
            "partial_update": TaskWriteSerializer,
        }.get(self.action, TaskDetailSerializer)

    def _detail_response(self, task, status_code=status.HTTP_200_OK):
        task = self.get_queryset().prefetch_related("blocked_by", "blocks").get(pk=task.pk)
        data = TaskDetailSerializer(task, context=self.get_serializer_context()).data
        return Response(data, status=status_code)

    def update(self, request, *args, **kwargs):
        task = self.get_object()  # scoped: staff 404 on non-member projects

        if request.user.role == User.Role.STAFF:
            # Matrix §8: staff "may edit status of OWN tasks" — nothing else.
            if task.assignee_id != request.user.id:
                raise PermissionDenied("You may only update tasks assigned to you.")
            extra = set(request.data) - {"status"}
            if extra:
                raise PermissionDenied("You may only change the status of your tasks.")

        serializer = TaskWriteSerializer(
            task, data=request.data, partial=True, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return self._detail_response(task)

    def destroy(self, request, *args, **kwargs):
        services.delete_task(task=self.get_object(), actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get", "post"], url_path="time-entries")
    def time_entries(self, request, pk=None):
        """
        GET  — the task's logged hours (staff see their OWN rows only, §8).
        POST — log time: {hours, worked_on, description?}. Any role that can
               see the task can log time on it; the row is always yours.
        """
        task = self.get_object()

        if request.method == "GET":
            qs = task.time_entries.select_related("user", "task")
            if request.user.role == User.Role.STAFF:
                qs = qs.filter(user=request.user)
            page = self.paginate_queryset(qs)
            data = TimeEntrySerializer(page, many=True).data
            return self.get_paginated_response(data)

        context = {**self.get_serializer_context(), "task": task}
        serializer = TimeEntryWriteSerializer(data=request.data, context=context)
        serializer.is_valid(raise_exception=True)
        entry = serializer.save()
        return Response(TimeEntrySerializer(entry).data, status=status.HTTP_201_CREATED)


class TimeEntryViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    Flat time-entry resource. The cross-task list is the report screen:
    GET /time-entries/?user=7&worked_from=2026-07-01&worked_to=2026-07-31
    PATCH/DELETE fix a mislogged row — owner or manager/admin (matrix §8:
    staff "own only", and their queryset is pre-filtered to own rows anyway).
    """

    owner_field = "user"  # read by IsOwnerOrManager
    http_method_names = ["get", "patch", "delete", "head", "options"]
    filterset_class = TimeEntryFilter
    ordering_fields = ["worked_on", "hours", "created_at"]
    ordering = ["-worked_on", "-id"]

    def get_permissions(self):
        perms = super().get_permissions()
        if self.action in ("partial_update", "destroy"):
            perms.append(IsOwnerOrManager())
        return perms

    def get_queryset(self):
        qs = TimeEntry.objects.filter(task__project__is_active=True).select_related(
            "user", "task", "task__project"
        )
        if self.request.user.role == User.Role.STAFF:
            qs = qs.filter(user=self.request.user)
        return qs

    def get_serializer_class(self):
        return TimeEntryWriteSerializer if self.action == "partial_update" else TimeEntrySerializer

    def update(self, request, *args, **kwargs):
        super().update(request, *args, **kwargs)
        return Response(TimeEntrySerializer(self.get_object()).data)


class TechnologyViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    """
    GET  /technologies/?search=dj   the tag picker (all roles)
    POST /technologies/             add a tag (manager/admin)
    No update/delete: renaming a tag silently rewrites every project it is on,
    and deleting one breaks saved filters — revisit only with a merge feature.
    """

    permission_classes = [ReadOnlyForStaff]
    queryset = Technology.objects.all()
    serializer_class = TechnologySerializer
    search_fields = ["name"]
    ordering = ["name"]
