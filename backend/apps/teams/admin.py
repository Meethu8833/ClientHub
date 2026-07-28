from django.contrib import admin

from .models import Department, Team, TeamMembership, TimeOff


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "head", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "department", "lead", "is_active", "created_at")
    list_filter = ("is_active", "department")
    search_fields = ("name",)


@admin.register(TeamMembership)
class TeamMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "team", "allocation_percent", "created_at")
    list_filter = ("team",)
    search_fields = ("user__email",)


@admin.register(TimeOff)
class TimeOffAdmin(admin.ModelAdmin):
    list_display = ("user", "type", "start_date", "end_date")
    list_filter = ("type",)
    search_fields = ("user__email",)
