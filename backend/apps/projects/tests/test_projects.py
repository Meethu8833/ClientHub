"""
Project API tests: permission matrix (§8 — manager/admin full, staff read-only
+ member-scoped), CRUD, validation, progress %, budget hiding, search/filter,
soft delete, history rows.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.activities.models import Activity
from apps.clients.models import Client
from apps.projects.models import Milestone, Project, ProjectMembership, Technology

PASSWORD = "Str0ng!pass123"

pytestmark = pytest.mark.django_db

LIST_URL = reverse("projects:project-list")


def detail_url(project_id):
    return reverse("projects:project-detail", args=[project_id])


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
def acme():
    return Client.objects.create(name="Acme Fintech", status=Client.Status.ACTIVE)


@pytest.fixture
def django_tech():
    return Technology.objects.create(name="Django")


def payload(client_id, **overrides):
    data = {
        "name": "Website Redesign",
        "client_id": client_id,
        "description": "Full rebuild of the marketing site.",
        "status": "in_progress",
        "priority": "high",
        "start_date": "2026-08-01",
        "end_date": "2026-11-30",
        "budget": "500000.00",
    }
    data.update(overrides)
    return data


@pytest.fixture
def project(acme, manager):
    p = Project.objects.create(
        client=acme, name="Website Redesign", status="in_progress", budget="500000.00"
    )
    ProjectMembership.objects.create(project=p, user=manager, role="manager")
    return p


# ------------------------------------------------------------- permissions


def test_anonymous_gets_401(api):
    assert api.get(LIST_URL).status_code == 401


def test_staff_cannot_write(staff_api, acme, project):
    assert staff_api.post(LIST_URL, payload(acme.id)).status_code == 403
    assert staff_api.patch(detail_url(project.id), {"status": "on_hold"}).status_code == 403
    assert staff_api.delete(detail_url(project.id)).status_code == 403


def test_staff_sees_only_member_projects(staff_api, staff, project, acme):
    other = Project.objects.create(client=acme, name="Mobile App")
    ProjectMembership.objects.create(project=other, user=staff, role="developer")

    res = staff_api.get(LIST_URL)
    assert res.status_code == 200
    assert [row["id"] for row in res.data["results"]] == [other.id]
    # Non-member project 404s (scoping via queryset — existence never leaks).
    assert staff_api.get(detail_url(project.id)).status_code == 404
    assert staff_api.get(detail_url(other.id)).status_code == 200


def test_budget_hidden_from_staff(staff_api, staff, project):
    ProjectMembership.objects.create(project=project, user=staff, role="developer")
    res = staff_api.get(detail_url(project.id))
    assert res.status_code == 200
    assert "budget" not in res.data


# -------------------------------------------------------------------- CRUD


def test_manager_creates_project(manager_api, acme, django_tech):
    res = manager_api.post(LIST_URL, payload(acme.id, technology_ids=[django_tech.id]))
    assert res.status_code == 201
    # Response is the detail shape: nested client + technologies, progress null.
    assert res.data["client"] == {"id": acme.id, "name": "Acme Fintech"}
    assert res.data["technologies"] == [{"id": django_tech.id, "name": "Django"}]
    assert res.data["budget"] == "500000.00"
    assert res.data["progress"] is None  # no milestones yet ≠ 0% done
    # created is on the timeline
    assert Activity.objects.filter(verb=Activity.Verb.CREATED).count() == 1


def test_duplicate_name_for_same_client_rejected(manager_api, acme, project):
    res = manager_api.post(LIST_URL, payload(acme.id, name=project.name))
    assert res.status_code == 400
    assert "name" in res.data


def test_same_name_for_other_client_ok(manager_api, project):
    other_client = Client.objects.create(name="Globex")
    res = manager_api.post(LIST_URL, payload(other_client.id, name=project.name))
    assert res.status_code == 201


def test_end_before_start_rejected(manager_api, acme):
    res = manager_api.post(
        LIST_URL, payload(acme.id, start_date="2026-08-01", end_date="2026-07-01")
    )
    assert res.status_code == 400
    assert "end_date" in res.data


def test_status_change_recorded_in_history(manager_api, project):
    res = manager_api.patch(detail_url(project.id), {"status": "on_hold"})
    assert res.status_code == 200
    event = Activity.objects.get(verb=Activity.Verb.STATUS_CHANGED)
    assert event.changes == {"field": "status", "from": "in_progress", "to": "on_hold"}


def test_project_cannot_move_between_clients(manager_api, project):
    other = Client.objects.create(name="Globex")
    res = manager_api.patch(detail_url(project.id), {"client_id": other.id})
    assert res.status_code == 400


def test_soft_delete(manager_api, project):
    assert manager_api.delete(detail_url(project.id)).status_code == 204
    project.refresh_from_db()
    assert project.is_active is False  # row survives for audit
    assert manager_api.get(detail_url(project.id)).status_code == 404
    assert Activity.objects.filter(verb=Activity.Verb.DELETED).exists()


# ---------------------------------------------------------------- progress


def test_progress_is_completed_over_total(manager_api, project):
    Milestone.objects.create(project=project, title="Design", due_date="2026-08-15")
    Milestone.objects.create(
        project=project, title="Build", due_date="2026-10-01", is_completed=True
    )
    res = manager_api.get(detail_url(project.id))
    assert res.data["progress"] == 50
    assert res.data["members"][0]["role"] == "manager"


# ------------------------------------------------------- search & filtering


def test_filter_by_status_and_priority(manager_api, acme, project):
    Project.objects.create(client=acme, name="Support Retainer", status="planned", priority="low")
    res = manager_api.get(LIST_URL, {"status": "in_progress"})
    assert [r["id"] for r in res.data["results"]] == [project.id]
    assert manager_api.get(LIST_URL, {"status": "not_a_status"}).status_code == 400


def test_filter_by_member(manager_api, manager, acme, project):
    Project.objects.create(client=acme, name="Unstaffed")
    res = manager_api.get(LIST_URL, {"member": manager.id})
    assert [r["id"] for r in res.data["results"]] == [project.id]


def test_filter_by_technology(manager_api, acme, project, django_tech):
    project.technologies.add(django_tech)
    Project.objects.create(client=acme, name="Other")
    res = manager_api.get(LIST_URL, {"technology": django_tech.id})
    assert [r["id"] for r in res.data["results"]] == [project.id]


def test_search_by_client_name(manager_api, project):
    globex = Client.objects.create(name="Globex")
    Project.objects.create(client=globex, name="ERP Rollout")
    res = manager_api.get(LIST_URL, {"search": "acme"})
    assert [r["id"] for r in res.data["results"]] == [project.id]


def test_member_count_not_inflated_by_joins(manager_api, staff, project):
    # 2 members × 3 milestones would COUNT 6 without distinct=True.
    ProjectMembership.objects.create(project=project, user=staff, role="developer")
    for i in range(3):
        Milestone.objects.create(project=project, title=f"M{i}", due_date="2026-09-01")
    res = manager_api.get(LIST_URL)
    row = res.data["results"][0]
    assert row["member_count"] == 2
    assert row["progress"] == 0  # 0 of 3 done — a real 0, not None
