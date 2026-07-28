"""
Query-string filters for /projects/ and /milestones/ (django-filter).

Filtering = exact narrowing (?status=in_progress), search = fuzzy text
(?search=redesign), sorting = ?ordering=-end_date. The viewsets combine all
three (§6).
"""

import django_filters

from .models import Milestone, Project, Sprint, Task, TimeEntry


class ProjectFilter(django_filters.FilterSet):
    # ?client=3 — all projects for one client (the client detail page tab)
    client = django_filters.NumberFilter()
    # ChoiceFilters 400 on values outside the enum instead of returning []
    status = django_filters.ChoiceFilter(choices=Project.Status.choices)
    priority = django_filters.ChoiceFilter(choices=Project.Priority.choices)
    # ?member=7 — "what is Dev working on" (spans the M2M join)
    member = django_filters.NumberFilter(field_name="members")
    # ?technology=2 — "all our Django projects" (by Technology id)
    technology = django_filters.NumberFilter(field_name="technologies")
    # Deadline windows: ?due_before=2026-09-30 → what must ship this quarter
    due_before = django_filters.DateFilter(field_name="end_date", lookup_expr="lte")
    due_after = django_filters.DateFilter(field_name="end_date", lookup_expr="gte")
    starts_after = django_filters.DateFilter(field_name="start_date", lookup_expr="gte")
    # Budget band (manager screens; the field is hidden from staff anyway)
    budget_min = django_filters.NumberFilter(field_name="budget", lookup_expr="gte")
    budget_max = django_filters.NumberFilter(field_name="budget", lookup_expr="lte")

    class Meta:
        model = Project
        fields = [
            "client",
            "status",
            "priority",
            "member",
            "technology",
            "due_before",
            "due_after",
            "starts_after",
            "budget_min",
            "budget_max",
        ]


class MilestoneFilter(django_filters.FilterSet):
    project = django_filters.NumberFilter()
    is_completed = django_filters.BooleanFilter()
    # ?is_completed=false&due_before=2026-08-03 → "deadlines this week"
    due_before = django_filters.DateFilter(field_name="due_date", lookup_expr="lte")
    due_after = django_filters.DateFilter(field_name="due_date", lookup_expr="gte")

    class Meta:
        model = Milestone
        fields = ["project", "is_completed", "due_before", "due_after"]


class SprintFilter(django_filters.FilterSet):
    # ?project=3 — the project's sprint list; ?status=completed → velocity data
    project = django_filters.NumberFilter()
    status = django_filters.ChoiceFilter(choices=Sprint.Status.choices)

    class Meta:
        model = Sprint
        fields = ["project", "status"]


class TaskFilter(django_filters.FilterSet):
    # ?project=3&status=in_progress — one kanban column
    project = django_filters.NumberFilter()
    milestone = django_filters.NumberFilter()
    # ?sprint=5 — the sprint board; ?backlog=true — un-planned work
    sprint = django_filters.NumberFilter()
    backlog = django_filters.BooleanFilter(field_name="sprint", lookup_expr="isnull")
    status = django_filters.ChoiceFilter(choices=Task.Status.choices)
    priority = django_filters.ChoiceFilter(choices=Task.Priority.choices)
    # ?assignee=7 — "what is on Dev's plate"; ?unassigned=true — the backlog
    assignee = django_filters.NumberFilter()
    unassigned = django_filters.BooleanFilter(field_name="assignee", lookup_expr="isnull")
    # ?status=todo&due_before=2026-08-03 → "at risk this week"
    due_before = django_filters.DateFilter(field_name="due_date", lookup_expr="lte")
    due_after = django_filters.DateFilter(field_name="due_date", lookup_expr="gte")

    class Meta:
        model = Task
        fields = [
            "project",
            "milestone",
            "sprint",
            "backlog",
            "status",
            "priority",
            "assignee",
            "unassigned",
            "due_before",
            "due_after",
        ]


class TimeEntryFilter(django_filters.FilterSet):
    """The timesheet/report screen: ?user=7&from=2026-07-01&to=2026-07-31."""

    task = django_filters.NumberFilter()
    project = django_filters.NumberFilter(field_name="task__project")
    user = django_filters.NumberFilter()
    # `from`/`to` are Python keywords — declare explicitly, not via Meta.fields
    worked_from = django_filters.DateFilter(field_name="worked_on", lookup_expr="gte")
    worked_to = django_filters.DateFilter(field_name="worked_on", lookup_expr="lte")

    class Meta:
        model = TimeEntry
        fields = ["task", "project", "user", "worked_from", "worked_to"]
