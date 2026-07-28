"""
Teams API tests: permission matrix (§8), CRUD, the 100 % allocation budget,
time-off scoping + overlap rules, soft delete, and the capacity math.
"""

from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.projects.models import Project, Task, TimeEntry
from apps.teams.models import Department, Team, TeamMembership, TimeOff
from apps.teams.services import team_capacity_report, workdays_between

PASSWORD = "Str0ng!pass123"

pytestmark = pytest.mark.django_db

DEPARTMENTS_URL = reverse("teams:department-list")
TEAMS_URL = reverse("teams:team-list")
TIME_OFF_URL = reverse("teams:time-off-list")


def department_url(dep_id):
    return reverse("teams:department-detail", args=[dep_id])


def team_url(team_id):
    return reverse("teams:team-detail", args=[team_id])


@pytest.fixture
def manager():
    return User.objects.create_user(
        email="manager@example.com", password=PASSWORD, first_name="Max", role=User.Role.MANAGER
    )


@pytest.fixture
def staff():
    return User.objects.create_user(
        email="staff@example.com", password=PASSWORD, first_name="Stan", role=User.Role.STAFF
    )


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def manager_api(api, manager):
    api.force_authenticate(user=manager)
    return api


@pytest.fixture
def staff_api(staff):
    c = APIClient()
    c.force_authenticate(user=staff)
    return c


@pytest.fixture
def engineering():
    return Department.objects.create(name="Engineering")


@pytest.fixture
def platform(engineering):
    return Team.objects.create(department=engineering, name="Platform")


# ------------------------------------------------------------- permissions


def test_anonymous_gets_401(api):
    assert api.get(DEPARTMENTS_URL).status_code == 401
    assert api.get(TEAMS_URL).status_code == 401


def test_staff_reads_but_cannot_write_org_structure(staff_api, engineering, platform):
    assert staff_api.get(DEPARTMENTS_URL).status_code == 200
    assert staff_api.get(team_url(platform.id)).status_code == 200
    assert staff_api.post(DEPARTMENTS_URL, {"name": "Design"}).status_code == 403
    assert staff_api.patch(department_url(engineering.id), {"name": "Eng"}).status_code == 403
    assert staff_api.delete(team_url(platform.id)).status_code == 403
    assert (
        staff_api.post(
            reverse("teams:team-members", args=[platform.id]), {"user_id": 1}
        ).status_code
        == 403
    )


def test_capacity_report_is_manager_only(staff_api, platform):
    url = reverse("teams:team-capacity", args=[platform.id])
    assert staff_api.get(url, {"from": "2026-08-03", "to": "2026-08-07"}).status_code == 403


# ------------------------------------------------------ departments & teams


def test_manager_creates_department_and_nested_team(manager_api, manager):
    res = manager_api.post(
        DEPARTMENTS_URL, {"name": "Design", "description": "UX & UI", "head_id": manager.id}
    )
    assert res.status_code == 201
    assert res.data["head"]["id"] == manager.id

    dep_id = res.data["id"]
    res = manager_api.post(
        reverse("teams:department-teams", args=[dep_id]),
        {"name": "Brand", "lead_id": manager.id},
    )
    assert res.status_code == 201
    assert res.data["department"]["id"] == dep_id
    assert res.data["lead"]["id"] == manager.id


def test_duplicate_active_department_name_400(manager_api, engineering):
    res = manager_api.post(DEPARTMENTS_URL, {"name": "engineering"})  # case-insensitive
    assert res.status_code == 400
    assert "name" in res.data


def test_duplicate_team_name_only_within_department(manager_api, engineering, platform):
    dup = manager_api.post(
        reverse("teams:department-teams", args=[engineering.id]), {"name": "Platform"}
    )
    assert dup.status_code == 400

    other = Department.objects.create(name="Design")
    ok = manager_api.post(reverse("teams:department-teams", args=[other.id]), {"name": "Platform"})
    assert ok.status_code == 201


def test_department_with_live_teams_cannot_be_deleted(manager_api, engineering, platform):
    assert manager_api.delete(department_url(engineering.id)).status_code == 400

    # Disband the team → the department may go; both are soft deletes.
    assert manager_api.delete(team_url(platform.id)).status_code == 204
    assert manager_api.delete(department_url(engineering.id)).status_code == 204
    engineering.refresh_from_db()
    platform.refresh_from_db()
    assert not engineering.is_active and not platform.is_active
    assert manager_api.get(department_url(engineering.id)).status_code == 404


# -------------------------------------------------------------- allocation


def test_add_member_and_allocation_budget(manager_api, engineering, platform, staff):
    members_url = reverse("teams:team-members", args=[platform.id])
    res = manager_api.post(members_url, {"user_id": staff.id, "allocation_percent": 60})
    assert res.status_code == 201

    # Same team again → 400 (unique seat).
    assert manager_api.post(members_url, {"user_id": staff.id}).status_code == 400

    # A second team may only take the remaining 40 %.
    mobile = Team.objects.create(department=engineering, name="Mobile")
    mobile_members = reverse("teams:team-members", args=[mobile.id])
    over = manager_api.post(mobile_members, {"user_id": staff.id, "allocation_percent": 50})
    assert over.status_code == 400
    assert "allocation_percent" in over.data
    assert (
        manager_api.post(
            mobile_members, {"user_id": staff.id, "allocation_percent": 40}
        ).status_code
        == 201
    )


def test_allocation_update_excludes_own_row(manager_api, platform, staff):
    membership = TeamMembership.objects.create(team=platform, user=staff, allocation_percent=60)
    url = reverse("teams:team-membership-detail", args=[membership.id])
    # 60 → 100 is fine: the old 60 must not count against the budget.
    res = manager_api.patch(url, {"allocation_percent": 100})
    assert res.status_code == 200
    assert res.data["allocation_percent"] == 100


def test_soft_deleted_team_frees_allocation(manager_api, engineering, platform, staff):
    TeamMembership.objects.create(team=platform, user=staff, allocation_percent=100)
    assert manager_api.delete(team_url(platform.id)).status_code == 204

    mobile = Team.objects.create(department=engineering, name="Mobile")
    res = manager_api.post(
        reverse("teams:team-members", args=[mobile.id]),
        {"user_id": staff.id, "allocation_percent": 100},
    )
    assert res.status_code == 201


# ---------------------------------------------------------------- time off


def test_staff_records_own_time_off_only(staff_api, staff, manager):
    ok = staff_api.post(
        TIME_OFF_URL,
        {"type": "vacation", "start_date": "2026-08-10", "end_date": "2026-08-14"},
    )
    assert ok.status_code == 201
    assert ok.data["user"]["id"] == staff.id
    assert ok.data["workdays"] == 5

    forged = staff_api.post(
        TIME_OFF_URL,
        {"user_id": manager.id, "start_date": "2026-08-17", "end_date": "2026-08-18"},
    )
    assert forged.status_code == 400


def test_staff_cannot_see_others_absences(staff_api, manager):
    other = TimeOff.objects.create(user=manager, start_date="2026-08-10", end_date="2026-08-12")
    assert staff_api.get(TIME_OFF_URL).data["count"] == 0
    # Out-of-scope ids 404 — existence never leaks (§8).
    assert staff_api.get(reverse("teams:time-off-detail", args=[other.id])).status_code == 404


def test_time_off_validation(manager_api, manager):
    backwards = manager_api.post(
        TIME_OFF_URL, {"start_date": "2026-08-14", "end_date": "2026-08-10"}
    )
    assert backwards.status_code == 400

    assert (
        manager_api.post(
            TIME_OFF_URL, {"start_date": "2026-08-10", "end_date": "2026-08-14"}
        ).status_code
        == 201
    )
    overlap = manager_api.post(TIME_OFF_URL, {"start_date": "2026-08-13", "end_date": "2026-08-20"})
    assert overlap.status_code == 400


# ---------------------------------------------------------------- capacity


def test_workdays_skip_weekends():
    from datetime import date

    # Mon 2026-08-03 … Sun 2026-08-09 → 5 weekdays.
    assert workdays_between(date(2026, 8, 3), date(2026, 8, 9)) == 5


def test_capacity_report_math(manager_api, platform, staff, manager):
    """
    Staff at 50 % of a 40 h week over Mon–Fri (5 workdays), one absence day:
      gross = 40 × 5/5 × 50 %      = 20 h (team slice)
      net   = 20 − 8 × 50 %        = 16 h
      person net = 40 − 8          = 32 h
      logged 10 h → utilization    = 10/32 = 31.25 → 31.2 %
      (Python's round() is banker's rounding: half goes to the EVEN digit —
      same behaviour as the velocity report.)
    """
    TeamMembership.objects.create(team=platform, user=staff, allocation_percent=50)
    TimeOff.objects.create(user=staff, start_date="2026-08-05", end_date="2026-08-05")

    client = Client.objects.create(name="Acme", status=Client.Status.ACTIVE)
    project = Project.objects.create(client=client, name="Site")
    task = Task.objects.create(project=project, title="Build")
    TimeEntry.objects.create(task=task, user=staff, hours=Decimal("10"), worked_on="2026-08-04")
    # Outside the window — must not count.
    TimeEntry.objects.create(task=task, user=staff, hours=Decimal("9"), worked_on="2026-08-10")

    res = manager_api.get(
        reverse("teams:team-capacity", args=[platform.id]),
        {"from": "2026-08-03", "to": "2026-08-07"},
    )
    assert res.status_code == 200
    assert res.data["workdays"] == 5
    (row,) = res.data["members"]
    assert row["allocation_percent"] == 50
    assert row["gross_capacity_hours"] == Decimal("20.00")
    assert row["time_off_days"] == 1
    assert row["net_capacity_hours"] == Decimal("16.00")
    assert row["logged_hours"] == Decimal("10.00")
    assert row["utilization_percent"] == 31.2
    assert res.data["totals"]["net_capacity_hours"] == Decimal("16.00")


def test_capacity_requires_valid_window(manager_api, platform):
    url = reverse("teams:team-capacity", args=[platform.id])
    assert manager_api.get(url).status_code == 400  # missing params
    assert manager_api.get(url, {"from": "nope", "to": "2026-08-07"}).status_code == 400
    assert manager_api.get(url, {"from": "2026-08-07", "to": "2026-08-03"}).status_code == 400


def test_capacity_clamps_time_off_to_window(platform, staff):
    from datetime import date

    TeamMembership.objects.create(team=platform, user=staff, allocation_percent=100)
    # Three-week vacation, but only 3 weekdays fall inside the window.
    TimeOff.objects.create(user=staff, start_date="2026-07-27", end_date="2026-08-14")

    report = team_capacity_report(team=platform, start=date(2026, 8, 3), end=date(2026, 8, 5))
    (row,) = report["members"]
    assert row["time_off_days"] == 3
    assert row["net_capacity_hours"] == Decimal("0.00")
    assert row["utilization_percent"] is None
