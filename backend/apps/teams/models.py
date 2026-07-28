"""
Team Management models (org structure — an app ADDED beyond the original
ARCHITECTURE.md list; the design rationale lives in docs/team-management.md).

Department     = a permanent box on the org chart ("Engineering", "Design").
Team           = a working group INSIDE a department ("Platform Team").
TeamMembership = WHO is on a team and HOW MUCH of their week is allocated to
                 it — the through table behind the Team↔User M2M. A person's
                 allocations across all active teams may never exceed 100 %.
TimeOff        = an absence window (vacation, sick…) — the availability record
                 that capacity planning subtracts.

Capacity itself is deliberately NOT a table: capacity is derived from
User.weekly_capacity_hours × allocation % × workdays − time off, computed
fresh per report (stored aggregates drift out of sync — same rule as project
progress %). Compare ProjectMembership: that one answers "who delivers project
X", this one answers "where does this person's WEEK go" — different questions,
different tables.
"""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel


class Department(TimeStampedModel):
    """
    Org-chart unit. Soft-deleted (§4): departments accumulate teams and
    history — audit data that must survive "delete".
    """

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    # SET_NULL: a department can be temporarily headless (head resigned);
    # PROTECT would block deleting a user for a purely organisational label.
    head = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="departments_headed",
    )
    is_active = models.BooleanField(default=True)  # soft delete

    class Meta:
        constraints = [
            # Two LIVE "Engineering" departments make the org chart ambiguous;
            # a soft-deleted one frees its name (same conditional pattern as
            # uniq_project_name_per_client).
            models.UniqueConstraint(
                fields=["name"], condition=Q(is_active=True), name="uniq_active_department_name"
            ),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name


class Team(TimeStampedModel):
    """
    A working group inside a department. PROTECT on department: a department
    with live teams cannot be hard-deleted (and the API's soft delete also
    refuses while active teams exist). Soft-deleted itself — a disbanded
    team's allocation history stays readable.
    """

    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="teams")
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    # The team lead is a pointer, not a membership role: leads often also sit
    # on other teams, and "who leads" must survive membership churn.
    lead = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="teams_led",
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="TeamMembership",
        related_name="teams",
        blank=True,
    )
    is_active = models.BooleanField(default=True)  # soft delete

    class Meta:
        constraints = [
            # "Platform" once per department; another department may reuse it.
            models.UniqueConstraint(
                fields=["department", "name"],
                condition=Q(is_active=True),
                name="uniq_active_team_name_per_department",
            ),
        ]
        indexes = [
            # The department page's hot query: "live teams of department X".
            models.Index(fields=["department", "is_active"]),
        ]
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.department.name})"


class TeamMembership(TimeStampedModel):
    """
    One person's seat on one team, with the share of their working week that
    seat consumes. CASCADE both ways — a seat is meaningless without either
    end (soft-deleting a team keeps its rows; they simply stop counting
    towards the 100 % budget because sums filter team__is_active=True).
    """

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="team_memberships"
    )
    # % of the person's week given to THIS team. The per-row 1–100 range is a
    # DB constraint below; the cross-team invariant (sum ≤ 100) spans rows,
    # which a row-level CHECK cannot see — the serializer enforces it.
    allocation_percent = models.PositiveSmallIntegerField(
        default=100, validators=[MinValueValidator(1), MaxValueValidator(100)]
    )

    class Meta:
        constraints = [
            # One seat per person per team — "add twice" is a 400, not a dup.
            models.UniqueConstraint(fields=["team", "user"], name="uniq_team_membership"),
            # DB backstop for the serializer's friendly 400 (racy writes).
            models.CheckConstraint(
                condition=Q(allocation_percent__gte=1) & Q(allocation_percent__lte=100),
                name="team_allocation_percent_range",
            ),
        ]
        ordering = ["-allocation_percent", "created_at"]  # biggest commitment first

    def __str__(self):
        return f"{self.user} {self.allocation_percent}% on {self.team.name}"


class TimeOff(TimeStampedModel):
    """
    An absence window — the availability ledger. Append-per-absence rows, not
    a per-day calendar: ranges compress storage and map 1:1 to how people
    actually request leave. Hard-deleted (§4): operational rows, like tasks.
    No approval workflow yet (deliberate scope cut — see docs); managers
    record/fix anyone's rows, staff only their own.
    """

    class Type(models.TextChoices):
        VACATION = "vacation", "Vacation"
        SICK_LEAVE = "sick_leave", "Sick leave"
        TRAINING = "training", "Training"
        PERSONAL = "personal", "Personal"
        OTHER = "other", "Other"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="time_off"
    )
    # DateFields, not DateTimes: leave is taken in days ("Mon–Wed"), never
    # timestamps. Inclusive on both ends; a one-day absence has start == end.
    start_date = models.DateField()
    end_date = models.DateField()
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.VACATION)
    reason = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name_plural = "time off"
        constraints = [
            # Same backstop pattern as project_end_not_before_start.
            models.CheckConstraint(
                condition=Q(end_date__gte=models.F("start_date")),
                name="time_off_end_not_before_start",
            ),
        ]
        indexes = [
            # The calendar/capacity query: "absences of X overlapping a window".
            models.Index(fields=["user", "start_date"]),
        ]
        ordering = ["-start_date", "-id"]

    def __str__(self):
        return f"{self.user} {self.type} {self.start_date}–{self.end_date}"
