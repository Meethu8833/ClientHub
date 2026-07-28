"""Django admin — a back-office escape hatch, not a user-facing screen."""

from django.contrib import admin

from .models import Milestone, Project, ProjectMembership, Sprint, Task, Technology, TimeEntry


class MembershipInline(admin.TabularInline):
    model = ProjectMembership
    extra = 0


class MilestoneInline(admin.TabularInline):
    model = Milestone
    extra = 0


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["name", "client", "status", "priority", "end_date", "is_active"]
    list_filter = ["status", "priority", "is_active"]
    search_fields = ["name", "client__name"]
    inlines = [MembershipInline, MilestoneInline]


@admin.register(Milestone)
class MilestoneAdmin(admin.ModelAdmin):
    list_display = ["title", "project", "due_date", "is_completed"]
    list_filter = ["is_completed"]


@admin.register(Sprint)
class SprintAdmin(admin.ModelAdmin):
    list_display = ["name", "project", "status", "start_date", "end_date", "completed_points"]
    list_filter = ["status"]
    search_fields = ["name", "project__name"]


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ["title", "project", "status", "priority", "assignee", "due_date"]
    list_filter = ["status", "priority"]
    search_fields = ["title", "project__name"]
    # Without these two, every row in the change form renders a full dropdown
    # of ALL users/tasks — raw_id keeps the admin usable at scale.
    raw_id_fields = ["assignee", "milestone", "sprint", "blocked_by"]


@admin.register(TimeEntry)
class TimeEntryAdmin(admin.ModelAdmin):
    list_display = ["task", "user", "hours", "worked_on"]
    list_filter = ["worked_on"]
    raw_id_fields = ["task", "user"]


admin.site.register(Technology)
