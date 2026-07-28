"""
Project Management models (ARCHITECTURE.md §4, §5 — Phase 4, first slice).

Project           = a delivery engagement for a client (the container).
ProjectMembership = WHO works on it and in WHAT capacity (manager/developer)
                    — the "through" table behind the Project↔User M2M.
Milestone         = a dated checkpoint inside a project ("Design sign-off",
                    "UAT complete"); progress % is derived from these.
Technology        = a tag ("Django", "React") projects share via a plain M2M.

Deviation from the ERD, documented: membership role uses DEVELOPER instead of
MEMBER — this CRM is for IT service companies, where the non-manager role on a
delivery team is a developer.
"""

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex, OpClass
from django.contrib.postgres.search import SearchVector
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Upper

from apps.core.models import TimeStampedModel


class Technology(TimeStampedModel):
    """
    A technology tag. A real table (not TextChoices) because the tech list is
    DATA that grows at runtime ("Rust" next month) — enums are for values that
    change only with code releases (§4 choice pattern).
    """

    name = models.CharField(max_length=50, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "technologies"

    def __str__(self):
        return self.name


class Project(TimeStampedModel):
    """
    A client engagement. Soft-deleted via `is_active` (§4): projects accumulate
    milestones, files, notes and (later) invoices — audit data that must
    survive "delete".
    """

    class Status(models.TextChoices):
        # The lifecycle is a one-way street with two parking bays: ON_HOLD is
        # a pause (can resume), CANCELLED and COMPLETED are terminal.
        PLANNED = "planned", "Planned"
        IN_PROGRESS = "in_progress", "In progress"
        ON_HOLD = "on_hold", "On hold"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    # -- what & for whom ------------------------------------------------------
    # PROTECT (§4): a client with delivery history cannot be hard-deleted.
    client = models.ForeignKey("clients.Client", on_delete=models.PROTECT, related_name="projects")
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)

    # -- lifecycle ------------------------------------------------------------
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLANNED)
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.MEDIUM)

    # -- schedule -------------------------------------------------------------
    # DateFields, not DateTimes: contracts say "by 30 September", not
    # "by 30 Sept 17:42 UTC". Nullable — a PLANNED project may not be dated yet.
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)  # the deadline

    # -- money ----------------------------------------------------------------
    # Decimal, never float (§11). 14,2 = up to 999,999,999,999.99.
    budget = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )

    # -- people & stack -------------------------------------------------------
    technologies = models.ManyToManyField(Technology, blank=True, related_name="projects")
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="ProjectMembership",
        related_name="projects",
        blank=True,
    )

    # -- soft delete ----------------------------------------------------------
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            # Same client can't have two LIVE "Website Redesign" projects; two
            # different clients can, and a soft-deleted project frees its name
            # (same conditional pattern as the GSTIN constraint on Client).
            models.UniqueConstraint(
                fields=["client", "name"],
                condition=Q(is_active=True),
                name="uniq_project_name_per_client",
            ),
            # The DB itself refuses an end before the start — the serializer
            # gives the friendly 400 first, this is the racy-write backstop.
            models.CheckConstraint(
                condition=Q(end_date__isnull=True)
                | Q(start_date__isnull=True)
                | Q(end_date__gte=models.F("start_date")),
                name="project_end_not_before_start",
            ),
        ]
        indexes = [
            # The list screen's hot filter (§4).
            models.Index(fields=["status", "is_active"]),
            # Global search, two access paths:
            # trigram GIN over Upper(name) → substring match ("edes" finds
            # "Website Redesign"; Upper because icontains compiles to
            # UPPER(name) LIKE …); expression GIN over to_tsvector → word
            # match with stemming across name+description. Either index is
            # only used when the query repeats its EXACT expression
            # (same fields, same config) — see apps/search/services.py.
            GinIndex(OpClass(Upper("name"), name="gin_trgm_ops"), name="project_name_trgm"),
            GinIndex(SearchVector("name", "description", config="english"), name="project_fts"),
        ]

    def __str__(self):
        return f"{self.name} ({self.client.name})"


class ProjectMembership(TimeStampedModel):
    """
    The through table of Project↔User: plain M2M says only "is on the team",
    the through model also says AS WHAT and SINCE WHEN (created_at = joined).
    CASCADE both ways — a membership is meaningless without either end.
    """

    class Role(models.TextChoices):
        MANAGER = "manager", "Manager"  # runs the project, manages the team
        DEVELOPER = "developer", "Developer"  # does the delivery work

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="project_memberships"
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.DEVELOPER)

    class Meta:
        constraints = [
            # One row per person per project — "add twice" is a 400, not a dup.
            models.UniqueConstraint(fields=["project", "user"], name="uniq_membership_per_project"),
        ]
        ordering = ["role", "created_at"]  # managers first (alphabetical luck), then by joined

    def __str__(self):
        return f"{self.user} as {self.role} on {self.project.name}"


class Milestone(TimeStampedModel):
    """
    A dated checkpoint. CASCADE (§4): milestones mean nothing outside their
    project. Progress % = completed / total milestones (computed in queries,
    never stored — stored aggregates drift out of sync).
    """

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="milestones")
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    due_date = models.DateField()  # a checkpoint without a date is a wish
    is_completed = models.BooleanField(default=False)
    # Set by the service when is_completed flips True; cleared on reopen.
    # Records WHEN it was actually finished vs due_date (planned).
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["due_date", "id"]  # timeline order; id breaks date ties deterministically

    def __str__(self):
        return f"{self.title} ({self.project.name})"


class Sprint(TimeStampedModel):
    """
    A Scrum sprint: a fixed TIMEBOX (usually 1–4 weeks) inside a project in
    which the team commits to a set of tasks. Tasks not in any sprint form
    the project's BACKLOG (Task.sprint is NULL).

    State machine: PLANNED → ACTIVE → COMPLETED, one-way, driven ONLY by the
    services (start_sprint / complete_sprint) — never by a plain PATCH, so the
    invariants (one active sprint per project, snapshots on completion) can't
    be bypassed. Hard-deleted, but ONLY while still PLANNED: active/completed
    sprints are velocity history and must survive.
    """

    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="sprints")
    name = models.CharField(max_length=100)  # "Sprint 7", "July II"
    # The sprint GOAL — one sentence of intent ("Ship checkout flow").
    goal = models.TextField(blank=True)

    # The timebox. Required — a sprint without dates is just a label; the
    # burndown's x-axis and the "ideal line" are derived from these.
    start_date = models.DateField()
    end_date = models.DateField()

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLANNED)
    # ACTUAL ceremony times (vs the PLANNED dates above) — service-managed.
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # SNAPSHOTS frozen by complete_sprint(), NULL until then. Needed because
    # completion sends unfinished tasks back to the backlog — recomputing from
    # live rows later would under-count. completed_points is the sprint's
    # VELOCITY contribution.
    total_points = models.PositiveIntegerField(null=True, blank=True)
    completed_points = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            # "Sprint 7" can exist once per project; other projects unaffected.
            models.UniqueConstraint(
                fields=["project", "name"], name="uniq_sprint_name_per_project"
            ),
            # Same backstop pattern as project_end_not_before_start.
            models.CheckConstraint(
                condition=Q(end_date__gte=models.F("start_date")),
                name="sprint_end_not_before_start",
            ),
            # THE Scrum invariant, enforced by the DB itself: a partial unique
            # index over only the rows WHERE status='active' — a second active
            # sprint in the same project is impossible even under racy writes.
            models.UniqueConstraint(
                fields=["project"],
                condition=Q(status="active"),
                name="one_active_sprint_per_project",
            ),
        ]
        ordering = ["-start_date", "-id"]  # newest sprint first

    def __str__(self):
        return f"{self.name} ({self.project.name})"


class Task(TimeStampedModel):
    """
    One unit of work inside a project (Phase 4, tasks slice — ERD §5).

    Lifecycle: TODO → IN_PROGRESS → REVIEW → DONE (any direction is legal;
    kanban columns move both ways). `status` answers "where in the workflow",
    `priority` answers "how important" — two independent axes, never merged.

    Hard-deleted (§4): tasks are operational rows, not audit records — but the
    delete goes through services.delete_task() which also removes the notes,
    documents and history rows pinned to the task (GenericFKs have NO database
    cascade; skipping this would leave orphans forever).
    """

    class Status(models.TextChoices):
        TODO = "todo", "To do"
        IN_PROGRESS = "in_progress", "In progress"
        REVIEW = "review", "Review"
        DONE = "done", "Done"

    # Deliberate duplication of Project.Priority: task urgency and project
    # urgency are different business dials — sharing the enum would couple
    # them so one could never gain a value without the other.
    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    # -- where it lives -------------------------------------------------------
    # CASCADE: a task is meaningless outside its project (§4).
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    # SET_NULL (§4): deleting a milestone un-groups its tasks, never kills them.
    milestone = models.ForeignKey(
        Milestone, on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks"
    )
    # NULL = the backlog. SET_NULL, same reasoning as milestone: removing a
    # (planned) sprint returns its tasks to the backlog, never deletes work.
    sprint = models.ForeignKey(
        Sprint, on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks"
    )

    # -- what -----------------------------------------------------------------
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)

    # -- lifecycle ------------------------------------------------------------
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TODO)
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.MEDIUM)
    due_date = models.DateField(null=True, blank=True)
    # Service-managed, same invariant as Milestone: status==DONE ⇔ completed_at
    # set. Records when it was ACTUALLY finished vs due_date (planned).
    completed_at = models.DateTimeField(null=True, blank=True)

    # -- who ------------------------------------------------------------------
    # SET_NULL (§4): unassigned tasks are valid — deleting a user must not
    # delete the team's work, only orphan it back to the backlog.
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
    )

    # -- sizing ---------------------------------------------------------------
    # Story points: RELATIVE effort (team convention, usually Fibonacci
    # 1,2,3,5,8,13). NULL = not yet estimated — a different fact from 0.
    # An integer, not Decimal: points are deliberately coarse, never money.
    story_points = models.PositiveSmallIntegerField(null=True, blank=True)

    # -- time budget ----------------------------------------------------------
    # The PLAN. The ACTUAL is never stored — it is Sum(time_entries.hours),
    # aggregated in queries (stored totals drift, same rule as progress %).
    estimated_hours = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )

    # -- dependencies ---------------------------------------------------------
    # Self-referential M2M. symmetrical=False because blocking has a
    # DIRECTION: "deploy blocked_by migration" must not imply the reverse.
    # The mirror view comes free as task.blocks (related_name).
    # Same-project / no-self / no-cycle rules live in the serializer —
    # M2M fields cannot carry DB constraints for graph properties.
    blocked_by = models.ManyToManyField(
        "self", symmetrical=False, blank=True, related_name="blocks"
    )

    class Meta:
        indexes = [
            # The kanban board's hot query: "tasks of project X by status" (§4).
            models.Index(fields=["project", "status"]),
            # Global search (same pair as Project: substring + stemmed words).
            GinIndex(OpClass(Upper("title"), name="gin_trgm_ops"), name="task_title_trgm"),
            GinIndex(SearchVector("title", "description", config="english"), name="task_fts"),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.project.name})"


class TimeEntry(TimeStampedModel):
    """
    One person's logged hours on one task on one day — an append-only LOG,
    not a counter. Totals are always aggregated from these rows, and Phase 8
    billing will invoice straight off them, which drives two choices:
    user is PROTECT (billable history must survive account deletion) and
    hours is Decimal (§11: money-adjacent numbers are never floats).
    """

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="time_entries")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="time_entries"
    )
    # 5,2 → up to 999.99, far above the real ceiling enforced below.
    hours = models.DecimalField(max_digits=5, decimal_places=2)
    worked_on = models.DateField()  # the day the work HAPPENED (created_at = the day it was logged)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name_plural = "time entries"
        constraints = [
            # DB backstop for the serializer's friendly 400: a single entry is
            # 0 < hours ≤ 24 — nobody logs a 30-hour day in one row.
            models.CheckConstraint(
                condition=Q(hours__gt=0) & Q(hours__lte=24),
                name="time_entry_hours_range",
            ),
        ]
        indexes = [
            # The timesheet screen: "what did X log this week" (§4).
            models.Index(fields=["user", "worked_on"]),
        ]
        ordering = ["-worked_on", "-id"]

    def __str__(self):
        return f"{self.hours}h by {self.user} on {self.task.title}"
