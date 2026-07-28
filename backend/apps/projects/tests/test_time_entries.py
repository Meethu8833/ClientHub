"""
Time-entry API tests: logging (user always = request.user), validation
(0 < hours ≤ 24, no future days), the §8 matrix (staff OWN rows only —
list, nested list, edit, delete), report filters, and the logged_hours
aggregate on tasks.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.projects.models import Project, ProjectMembership, Task, TimeEntry

PASSWORD = "Str0ng!pass123"

pytestmark = pytest.mark.django_db

LIST_URL = reverse("projects:time-entry-list")
TODAY = timezone.localdate()


def log_url(task_id):
    return reverse("projects:task-time-entries", args=[task_id])


def detail_url(entry_id):
    return reverse("projects:time-entry-detail", args=[entry_id])


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
def manager_api(manager):
    c = APIClient()
    c.force_authenticate(user=manager)
    return c


@pytest.fixture
def staff_api(staff):
    c = APIClient()
    c.force_authenticate(user=staff)
    return c


@pytest.fixture
def task(manager, staff):
    client = Client.objects.create(name="Acme Fintech", status=Client.Status.ACTIVE)
    project = Project.objects.create(client=client, name="Website Redesign")
    ProjectMembership.objects.create(project=project, user=manager, role="manager")
    ProjectMembership.objects.create(project=project, user=staff, role="developer")
    return Task.objects.create(project=project, title="Build login page", assignee=staff)


@pytest.fixture
def staff_entry(task, staff):
    return TimeEntry.objects.create(task=task, user=staff, hours="2.00", worked_on=TODAY)


@pytest.fixture
def manager_entry(task, manager):
    return TimeEntry.objects.create(task=task, user=manager, hours="1.50", worked_on=TODAY)


# ------------------------------------------------------------------ logging


def test_member_logs_time_as_themselves(staff_api, staff, task):
    res = staff_api.post(
        log_url(task.id), {"hours": "2.50", "worked_on": str(TODAY), "description": "login form"}
    )
    assert res.status_code == 201
    # user comes from the session, NEVER from the body — no padding colleagues'
    # timesheets. (A user_id in the payload is simply ignored.)
    assert res.data["user"]["id"] == staff.id
    assert res.data["hours"] == "2.50"


def test_hours_must_be_a_sane_day_fraction(staff_api, task):
    for bad in ("0", "25"):
        res = staff_api.post(log_url(task.id), {"hours": bad, "worked_on": str(TODAY)})
        assert res.status_code == 400


def test_cannot_log_time_in_the_future(staff_api, task):
    tomorrow = TODAY + timedelta(days=1)
    res = staff_api.post(log_url(task.id), {"hours": "2.00", "worked_on": str(tomorrow)})
    assert res.status_code == 400
    assert "worked_on" in res.data


def test_logged_hours_aggregates_on_the_task(manager_api, task, staff_entry, manager_entry):
    res = manager_api.get(reverse("projects:task-detail", args=[task.id]))
    assert res.data["logged_hours"] == "3.50"  # 2.00 + 1.50, summed in SQL


# ------------------------------------------------------------------ scoping


def test_staff_sees_only_own_entries(staff_api, staff_entry, manager_entry, task):
    # Nested list on the task…
    res = staff_api.get(log_url(task.id))
    assert [r["id"] for r in res.data["results"]] == [staff_entry.id]
    # …and the flat report list: same rule (§8 "own only").
    res = staff_api.get(LIST_URL)
    assert [r["id"] for r in res.data["results"]] == [staff_entry.id]
    # A foreign row 404s — scoped queryset, existence never leaks.
    assert staff_api.get(detail_url(manager_entry.id)).status_code == 404


def test_manager_sees_all_and_can_filter(manager_api, staff, staff_entry, manager_entry):
    res = manager_api.get(LIST_URL)
    assert res.data["count"] == 2

    res = manager_api.get(LIST_URL, {"user": staff.id})
    assert [r["id"] for r in res.data["results"]] == [staff_entry.id]

    res = manager_api.get(LIST_URL, {"worked_to": str(TODAY - timedelta(days=1))})
    assert res.data["count"] == 0


# ------------------------------------------------------------- corrections


def test_staff_fixes_own_entry_only(staff_api, staff_entry, manager_entry):
    res = staff_api.patch(detail_url(staff_entry.id), {"hours": "3.00"})
    assert res.status_code == 200
    assert res.data["hours"] == "3.00"

    assert staff_api.patch(detail_url(manager_entry.id), {"hours": "0.10"}).status_code == 404
    assert staff_api.delete(detail_url(manager_entry.id)).status_code == 404
    assert staff_api.delete(detail_url(staff_entry.id)).status_code == 204


def test_manager_can_fix_anyones_entry(manager_api, staff_entry):
    assert manager_api.patch(detail_url(staff_entry.id), {"hours": "1.00"}).status_code == 200
    assert manager_api.delete(detail_url(staff_entry.id)).status_code == 204
