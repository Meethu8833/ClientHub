"""
Serializers for the projects app (§6 conventions):

- ProjectListSerializer    — slim table rows (+ progress, member_count)
- ProjectDetailSerializer  — full record with team, milestones, tech stack
- ProjectWriteSerializer   — POST/PATCH body (writes accept _id fields)
- Membership / Milestone / Technology serializers — same read/write split

Money rule: `budget` appears ONLY in the detail shape and is stripped for
STAFF — commercial terms are management information.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from apps.clients.models import Client

from . import services
from .models import Milestone, Project, ProjectMembership, Sprint, Task, Technology, TimeEntry

User = get_user_model()


class TechnologySerializer(serializers.ModelSerializer):
    class Meta:
        model = Technology
        fields = ["id", "name"]


class ClientMiniSerializer(serializers.ModelSerializer):
    """Just enough to render a link chip: 'Acme Fintech ↗'."""

    class Meta:
        model = Client
        fields = ["id", "name"]


class UserMiniSerializer(serializers.ModelSerializer):
    """Mini user embedded in reads: {id, name, email}."""

    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "name", "email"]

    def get_name(self, obj):
        return obj.get_full_name() or obj.email


# ---------------------------------------------------------------- membership


class MembershipSerializer(serializers.ModelSerializer):
    """Read shape for one team row. created_at doubles as 'joined' date."""

    user = UserMiniSerializer(read_only=True)

    class Meta:
        model = ProjectMembership
        fields = ["id", "project", "user", "role", "created_at"]
        read_only_fields = fields


class MembershipCreateSerializer(serializers.Serializer):
    """POST /projects/{id}/members/ body: {user_id, role}."""

    user_id = serializers.PrimaryKeyRelatedField(source="user", queryset=User.objects.none())
    role = serializers.ChoiceField(
        choices=ProjectMembership.Role.choices, default=ProjectMembership.Role.DEVELOPER
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Soft-deleted users can't join teams; evaluated per request.
        self.fields["user_id"].queryset = User.objects.alive()

    def validate(self, attrs):
        project = self.context["project"]
        if project.memberships.filter(user=attrs["user"]).exists():
            # Friendly 400 before the DB unique constraint 500s.
            raise serializers.ValidationError(
                {"user_id": "This user is already a member of the project."}
            )
        return attrs

    def create(self, validated_data):
        return services.add_member(
            project=self.context["project"],
            user=validated_data["user"],
            role=validated_data["role"],
            actor=self.context["request"].user,
        )


class MembershipUpdateSerializer(serializers.Serializer):
    """PATCH /project-memberships/{id}/ may change the role, nothing else."""

    role = serializers.ChoiceField(choices=ProjectMembership.Role.choices)


# ----------------------------------------------------------------- milestone


class MilestoneSerializer(serializers.ModelSerializer):
    # Computed, not stored: "overdue" depends on what day it is.
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = Milestone
        fields = [
            "id",
            "project",
            "title",
            "description",
            "due_date",
            "is_completed",
            "completed_at",
            "is_overdue",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_is_overdue(self, obj):
        return not obj.is_completed and obj.due_date < timezone.localdate()


class MilestoneWriteSerializer(serializers.ModelSerializer):
    """
    Create/update body. `project` is injected from the URL on nested create
    and immutable afterwards; `completed_at` is service-managed, never
    client-set (a caller could otherwise forge completion times).
    """

    class Meta:
        model = Milestone
        fields = ["title", "description", "due_date", "is_completed"]

    def save(self, **kwargs):
        # Route through the service so completed_at + the history row stay
        # consistent no matter which endpoint saved.
        instance = self.instance or Milestone(**kwargs)
        for attr, value in self.validated_data.items():
            setattr(instance, attr, value)
        self.instance = services.save_milestone(
            milestone=instance, actor=self.context["request"].user
        )
        return self.instance


# ------------------------------------------------------------------- project


class _ProgressMixin(serializers.Serializer):
    """
    progress = completed / total milestones, as an int percent.
    Reads the milestone_total/milestone_done annotations the viewset computes
    in SQL — no per-row queries. None (not 0) when there are no milestones:
    "nothing planned yet" and "0% done" are different facts.
    """

    progress = serializers.SerializerMethodField()

    def get_progress(self, obj):
        total = obj.milestone_total
        return round(obj.milestone_done * 100 / total) if total else None


class ProjectListSerializer(_ProgressMixin, serializers.ModelSerializer):
    """One table row. No budget here — money is detail-only, role-gated."""

    client = ClientMiniSerializer(read_only=True)
    technologies = TechnologySerializer(many=True, read_only=True)
    member_count = serializers.IntegerField(read_only=True)  # annotated

    class Meta:
        model = Project
        fields = [
            "id",
            "name",
            "client",
            "status",
            "priority",
            "start_date",
            "end_date",
            "progress",
            "member_count",
            "technologies",
            "created_at",
        ]


class ProjectDetailSerializer(_ProgressMixin, serializers.ModelSerializer):
    """Full record for the detail page: team, milestones, stack, money."""

    client = ClientMiniSerializer(read_only=True)
    technologies = TechnologySerializer(many=True, read_only=True)
    members = MembershipSerializer(source="memberships", many=True, read_only=True)
    milestones = MilestoneSerializer(many=True, read_only=True)

    class Meta:
        model = Project
        fields = [
            "id",
            "name",
            "client",
            "description",
            "status",
            "priority",
            "start_date",
            "end_date",
            "budget",
            "progress",
            "technologies",
            "members",
            "milestones",
            "created_at",
            "updated_at",
        ]

    def get_fields(self):
        # Field-level security: STAFF never see commercial terms. Done here
        # (server-side, per request) — hiding the column in React is UX only.
        fields = super().get_fields()
        request = self.context.get("request")
        if request and request.user.role == User.Role.STAFF:
            fields.pop("budget")
        return fields


class ProjectWriteSerializer(serializers.ModelSerializer):
    """POST/PATCH body. Reads embed objects; writes accept plain ids (§6)."""

    client_id = serializers.PrimaryKeyRelatedField(source="client", queryset=Client.objects.none())
    technology_ids = serializers.PrimaryKeyRelatedField(
        source="technologies",
        queryset=Technology.objects.all(),
        many=True,
        required=False,
    )

    class Meta:
        model = Project
        fields = [
            "name",
            "client_id",
            "description",
            "status",
            "priority",
            "start_date",
            "end_date",
            "budget",
            "technology_ids",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # No projects for soft-deleted clients; on update the client is fixed.
        self.fields["client_id"].queryset = Client.objects.filter(is_active=True)
        if self.instance is not None:
            self.fields["client_id"].required = False

    def validate(self, attrs):
        def get(field):
            # PATCH sends only changed fields — cross-field checks must read
            # "the new value if sent, else the current one".
            return attrs.get(field, getattr(self.instance, field, None))

        if self.instance and "client" in attrs and attrs["client"] != self.instance.client:
            raise serializers.ValidationError(
                {"client_id": "A project cannot be moved to another client."}
            )

        start, end = get("start_date"), get("end_date")
        if start and end and end < start:
            raise serializers.ValidationError(
                {"end_date": "End date cannot be before the start date."}
            )

        name, client = get("name"), get("client")
        if (
            name
            and client
            and Project.objects.exclude(pk=getattr(self.instance, "pk", None))
            .filter(client=client, name=name, is_active=True)
            .exists()
        ):
            raise serializers.ValidationError(
                {"name": "This client already has a project with this name."}
            )
        return attrs

    def save(self, **kwargs):
        technologies = self.validated_data.pop("technologies", None)
        creating = self.instance is None
        instance = self.instance or Project(**kwargs)
        for attr, value in self.validated_data.items():
            setattr(instance, attr, value)
        actor = self.context["request"].user
        if creating:
            self.instance = services.create_project(
                project=instance, technologies=technologies or [], actor=actor
            )
        else:
            self.instance = services.update_project(
                project=instance, technologies=technologies, actor=actor
            )
        return self.instance


# -------------------------------------------------------------------- sprint


class SprintMiniSerializer(serializers.ModelSerializer):
    """Chip on a task card: 'Sprint 7 (active)'."""

    class Meta:
        model = Sprint
        fields = ["id", "name", "status"]


class SprintSerializer(serializers.ModelSerializer):
    """
    Read shape. Two kinds of numbers, deliberately distinct:
    - task_count / points_committed — LIVE annotations (what is in the sprint
      right now); on a completed sprint they cover only the tasks that stayed
      (the done ones), because completion sends the rest back to the backlog.
    - total_points / completed_points — SNAPSHOTS frozen at completion, null
      before it. History reads these, never the live numbers.
    """

    task_count = serializers.IntegerField(read_only=True)  # annotated
    points_committed = serializers.IntegerField(read_only=True)  # annotated

    class Meta:
        model = Sprint
        fields = [
            "id",
            "project",
            "name",
            "goal",
            "start_date",
            "end_date",
            "status",
            "started_at",
            "completed_at",
            "task_count",
            "points_committed",
            "total_points",
            "completed_points",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class SprintWriteSerializer(serializers.ModelSerializer):
    """
    POST /projects/{id}/sprints/ and PATCH /sprints/{id}/ body.

    No `status` field ON PURPOSE: the lifecycle moves only through the
    /start/ and /complete/ actions (state machine over PATCH) — otherwise a
    client could jump straight to COMPLETED and skip the snapshot logic.
    `project` comes from the URL on create and is immutable after.
    """

    class Meta:
        model = Sprint
        fields = ["name", "goal", "start_date", "end_date"]

    def _project(self):
        return self.context.get("project") or self.instance.project

    def validate(self, attrs):
        if self.instance and self.instance.status == Sprint.Status.COMPLETED:
            # Completed sprints are history — velocity reports point at them.
            raise serializers.ValidationError("A completed sprint cannot be edited.")

        def get(field):
            # PATCH sends only changed fields — read "new if sent, else current".
            return attrs.get(field, getattr(self.instance, field, None))

        start, end = get("start_date"), get("end_date")
        if start and end and end < start:
            raise serializers.ValidationError(
                {"end_date": "End date cannot be before the start date."}
            )

        name = attrs.get("name")
        if (
            name
            and Sprint.objects.exclude(pk=getattr(self.instance, "pk", None))
            .filter(project=self._project(), name=name)
            .exists()
        ):
            raise serializers.ValidationError(
                {"name": "This project already has a sprint with this name."}
            )
        return attrs


# ---------------------------------------------------------------------- task


class ProjectMiniSerializer(serializers.ModelSerializer):
    """Link chip for rows that hang off a project."""

    class Meta:
        model = Project
        fields = ["id", "name"]


class MilestoneMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Milestone
        fields = ["id", "title"]


class TaskMiniSerializer(serializers.ModelSerializer):
    """Dependency chip: enough to render 'blocked by: DB migration (todo)'."""

    class Meta:
        model = Task
        fields = ["id", "title", "status"]


class _TaskReadMixin(serializers.Serializer):
    """
    Shared computed fields. logged_hours / open_blockers are read from viewset
    annotations (SQL, one query for the whole page) — never per-row Python.
    """

    is_overdue = serializers.SerializerMethodField()
    logged_hours = serializers.DecimalField(max_digits=8, decimal_places=2, read_only=True)
    open_blockers = serializers.IntegerField(read_only=True)

    def get_is_overdue(self, obj):
        # DONE tasks are never overdue; undated tasks can't be.
        return bool(
            obj.due_date and obj.status != Task.Status.DONE and obj.due_date < timezone.localdate()
        )


class TaskListSerializer(_TaskReadMixin, serializers.ModelSerializer):
    """One kanban card / table row — slim, no description, no dependency lists."""

    project = ProjectMiniSerializer(read_only=True)
    milestone = MilestoneMiniSerializer(read_only=True)
    sprint = SprintMiniSerializer(read_only=True)
    assignee = UserMiniSerializer(read_only=True)

    class Meta:
        model = Task
        fields = [
            "id",
            "title",
            "project",
            "milestone",
            "sprint",
            "status",
            "priority",
            "assignee",
            "due_date",
            "is_overdue",
            "story_points",
            "estimated_hours",
            "logged_hours",
            "open_blockers",
            "created_at",
        ]


class TaskDetailSerializer(_TaskReadMixin, serializers.ModelSerializer):
    """Full record for the task modal: both sides of the dependency graph."""

    project = ProjectMiniSerializer(read_only=True)
    milestone = MilestoneMiniSerializer(read_only=True)
    sprint = SprintMiniSerializer(read_only=True)
    assignee = UserMiniSerializer(read_only=True)
    blocked_by = TaskMiniSerializer(many=True, read_only=True)  # what must finish first
    blocks = TaskMiniSerializer(many=True, read_only=True)  # what is waiting on this

    class Meta:
        model = Task
        fields = [
            "id",
            "title",
            "description",
            "project",
            "milestone",
            "sprint",
            "status",
            "priority",
            "assignee",
            "due_date",
            "is_overdue",
            "completed_at",
            "story_points",
            "estimated_hours",
            "logged_hours",
            "open_blockers",
            "blocked_by",
            "blocks",
            "created_at",
            "updated_at",
        ]


def _would_cycle(task: Task, blockers) -> bool:
    """
    Dependencies form a directed graph; a cycle (A blocks B blocks A) would
    deadlock both tasks forever. Walk UP from each proposed blocker through
    ITS blockers, breadth-first over the M2M through table — if we ever reach
    `task` itself, the proposed edge closes a loop.
    """
    through = Task.blocked_by.through
    seen = set()
    frontier = {b.pk for b in blockers}
    while frontier:
        if task.pk in frontier:
            return True
        seen |= frontier
        frontier = (
            set(
                through.objects.filter(from_task_id__in=frontier).values_list(
                    "to_task_id", flat=True
                )
            )
            - seen
        )  # never revisit: guarantees termination even on weird data
    return False


class TaskWriteSerializer(serializers.ModelSerializer):
    """
    POST /projects/{id}/tasks/ and PATCH /tasks/{id}/ body. Reads embed
    objects, writes accept _id fields (§6). `project` comes from the URL on
    create (context) and is immutable after — a task never changes project.
    `completed_at` is service-managed, never client-set.
    """

    milestone_id = serializers.PrimaryKeyRelatedField(
        source="milestone", queryset=Milestone.objects.all(), required=False, allow_null=True
    )
    sprint_id = serializers.PrimaryKeyRelatedField(
        source="sprint", queryset=Sprint.objects.all(), required=False, allow_null=True
    )
    assignee_id = serializers.PrimaryKeyRelatedField(
        source="assignee", queryset=User.objects.none(), required=False, allow_null=True
    )
    blocked_by_ids = serializers.PrimaryKeyRelatedField(
        source="blocked_by", queryset=Task.objects.all(), many=True, required=False
    )

    class Meta:
        model = Task
        fields = [
            "title",
            "description",
            "status",
            "priority",
            "due_date",
            "story_points",
            "estimated_hours",
            "milestone_id",
            "sprint_id",
            "assignee_id",
            "blocked_by_ids",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assignee_id"].queryset = User.objects.alive()

    def _project(self):
        # Nested create carries the project in context; on update it is fixed.
        return self.context.get("project") or self.instance.project

    def validate(self, attrs):
        project = self._project()

        def get(field):
            # PATCH sends only changed fields — read "new if sent, else current".
            return attrs.get(field, getattr(self.instance, field, None))

        milestone = attrs.get("milestone")
        if milestone and milestone.project_id != project.pk:
            raise serializers.ValidationError(
                {"milestone_id": "This milestone belongs to a different project."}
            )

        sprint = attrs.get("sprint")
        if sprint:
            if sprint.project_id != project.pk:
                raise serializers.ValidationError(
                    {"sprint_id": "This sprint belongs to a different project."}
                )
            if sprint.status == Sprint.Status.COMPLETED:
                # A completed sprint is frozen history — its numbers already
                # feed velocity; adding tasks would rewrite the past.
                raise serializers.ValidationError(
                    {"sprint_id": "Cannot add tasks to a completed sprint."}
                )

        # You can only hand work to someone who is ON the project — otherwise
        # a task would be invisible to its own assignee (staff scoping §8).
        assignee = attrs.get("assignee")
        if assignee and not project.memberships.filter(user=assignee).exists():
            raise serializers.ValidationError(
                {"assignee_id": "This user is not a member of the project — add them first."}
            )

        blockers = attrs.get("blocked_by")
        if blockers is not None:
            if any(b.project_id != project.pk for b in blockers):
                raise serializers.ValidationError(
                    {"blocked_by_ids": "Dependencies must be tasks of the same project."}
                )
            if self.instance and any(b.pk == self.instance.pk for b in blockers):
                raise serializers.ValidationError({"blocked_by_ids": "A task cannot block itself."})
            if self.instance and _would_cycle(self.instance, blockers):
                raise serializers.ValidationError(
                    {"blocked_by_ids": "This would create a dependency cycle."}
                )

        # The dependency GATE: a blocked task stays in TODO until every
        # blocker is done. Checked against the effective (new-or-current) set.
        status = get("status") or Task.Status.TODO
        if status != Task.Status.TODO:
            effective = (
                blockers
                if blockers is not None
                else (list(self.instance.blocked_by.all()) if self.instance else [])
            )
            open_titles = [b.title for b in effective if b.status != Task.Status.DONE]
            if open_titles:
                raise serializers.ValidationError(
                    {"status": f"Blocked by unfinished task(s): {', '.join(open_titles)}."}
                )
        return attrs

    def save(self, **kwargs):
        blocked_by = self.validated_data.pop("blocked_by", None)
        instance = self.instance or Task(**kwargs)  # kwargs = {project: ...} on nested create
        for attr, value in self.validated_data.items():
            setattr(instance, attr, value)
        self.instance = services.save_task(
            task=instance, blocked_by=blocked_by, actor=self.context["request"].user
        )
        return self.instance


# ----------------------------------------------------------------- time entry


class TimeEntrySerializer(serializers.ModelSerializer):
    """Read shape: one logged-hours row on a task's time tab / the timesheet."""

    user = UserMiniSerializer(read_only=True)
    task = TaskMiniSerializer(read_only=True)

    class Meta:
        model = TimeEntry
        fields = ["id", "task", "user", "hours", "worked_on", "description", "created_at"]
        read_only_fields = fields


class TimeEntryWriteSerializer(serializers.ModelSerializer):
    """
    POST /tasks/{id}/time-entries/ and PATCH /time-entries/{id}/ body.
    task comes from the URL, user is ALWAYS request.user — you log your own
    time; letting callers pick a user_id would let anyone pad a colleague's
    timesheet (and later, the client's invoice).
    """

    hours = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0.01"),
        max_value=Decimal("24"),
    )

    class Meta:
        model = TimeEntry
        fields = ["hours", "worked_on", "description"]

    def validate_worked_on(self, value):
        if value > timezone.localdate():
            raise serializers.ValidationError("Cannot log time in the future.")
        return value

    def create(self, validated_data):
        return TimeEntry.objects.create(
            task=self.context["task"], user=self.context["request"].user, **validated_data
        )
