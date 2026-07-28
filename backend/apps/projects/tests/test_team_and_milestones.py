"""
Team (membership) and milestone tests: nested create, flat writes, the
last-manager guard, completed_at lifecycle, deadline filters, and the
history/notes wiring for projects.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.activities.models import Activity
from apps.clients.models import Client
from apps.projects.models import Milestone, Project, ProjectMembership

PASSWORD = "Str0ng!pass123"

pytestmark = pytest.mark.django_db


def members_url(project_id):
    return reverse("projects:project-members", args=[project_id])


def milestones_url(project_id):
    return reverse("projects:project-milestones", args=[project_id])


def membership_url(membership_id):
    return reverse("projects:membership-detail", args=[membership_id])


def milestone_url(milestone_id):
    return reverse("projects:milestone-detail", args=[milestone_id])


@pytest.fixture
def manager():
    return User.objects.create_user(
        email="manager@example.com", password=PASSWORD, first_name="Max", role=User.Role.MANAGER
    )


@pytest.fixture
def dev():
    return User.objects.create_user(
        email="dev@example.com", password=PASSWORD, first_name="Dev", role=User.Role.STAFF
    )


@pytest.fixture
def manager_api(manager):
    c = APIClient()
    c.force_authenticate(user=manager)
    return c


@pytest.fixture
def dev_api(dev):
    c = APIClient()
    c.force_authenticate(user=dev)
    return c


@pytest.fixture
def project(manager):
    client = Client.objects.create(name="Acme Fintech")
    p = Project.objects.create(client=client, name="Website Redesign")
    ProjectMembership.objects.create(project=p, user=manager, role="manager")
    return p


# ------------------------------------------------------------------- team


def test_manager_adds_member(manager_api, project, dev):
    res = manager_api.post(members_url(project.id), {"user_id": dev.id, "role": "developer"})
    assert res.status_code == 201
    assert res.data["user"]["name"] == "Dev"
    assert res.data["role"] == "developer"
    event = Activity.objects.get(verb=Activity.Verb.MEMBER_ADDED)
    assert event.changes["user_id"] == dev.id


def test_adding_twice_is_400(manager_api, project, dev):
    manager_api.post(members_url(project.id), {"user_id": dev.id})
    res = manager_api.post(members_url(project.id), {"user_id": dev.id})
    assert res.status_code == 400
    assert "user_id" in res.data


def test_staff_cannot_manage_team(dev_api, project, dev):
    ProjectMembership.objects.create(project=project, user=dev, role="developer")
    assert dev_api.post(members_url(project.id), {"user_id": dev.id}).status_code == 403
    membership = project.memberships.get(user=dev)
    assert dev_api.delete(membership_url(membership.id)).status_code == 403


def test_remove_member_and_history(manager_api, project, dev):
    membership = ProjectMembership.objects.create(project=project, user=dev, role="developer")
    assert manager_api.delete(membership_url(membership.id)).status_code == 204
    assert not project.memberships.filter(user=dev).exists()
    assert Activity.objects.filter(verb=Activity.Verb.MEMBER_REMOVED).exists()


def test_last_manager_cannot_be_removed_or_demoted(manager_api, project, manager):
    membership = project.memberships.get(user=manager)
    assert manager_api.delete(membership_url(membership.id)).status_code == 400
    res = manager_api.patch(membership_url(membership.id), {"role": "developer"})
    assert res.status_code == 400
    membership.refresh_from_db()
    assert membership.role == "manager"


def test_role_change_recorded(manager_api, project, dev):
    membership = ProjectMembership.objects.create(project=project, user=dev, role="developer")
    res = manager_api.patch(membership_url(membership.id), {"role": "manager"})
    assert res.status_code == 200
    event = Activity.objects.get(verb=Activity.Verb.MEMBER_ROLE_CHANGED)
    assert event.changes["to"] == "manager"


# -------------------------------------------------------------- milestones


def test_nested_create_and_flat_complete(manager_api, project):
    res = manager_api.post(
        milestones_url(project.id),
        {"title": "Design sign-off", "due_date": "2026-08-15"},
    )
    assert res.status_code == 201
    assert res.data["is_completed"] is False
    assert res.data["completed_at"] is None

    res = manager_api.patch(milestone_url(res.data["id"]), {"is_completed": True})
    assert res.status_code == 200
    assert res.data["completed_at"] is not None  # stamped by the service
    assert Activity.objects.filter(verb=Activity.Verb.MILESTONE_COMPLETED).exists()


def test_reopening_clears_completed_at(manager_api, project):
    m = Milestone.objects.create(
        project=project, title="Build", due_date="2026-09-01", is_completed=False
    )
    manager_api.patch(milestone_url(m.id), {"is_completed": True})
    res = manager_api.patch(milestone_url(m.id), {"is_completed": False})
    assert res.data["completed_at"] is None
    assert Activity.objects.filter(verb=Activity.Verb.MILESTONE_REOPENED).exists()


def test_overdue_is_computed(manager_api, project):
    m = Milestone.objects.create(project=project, title="Late", due_date="2020-01-01")
    res = manager_api.get(milestone_url(m.id))
    assert res.data["is_overdue"] is True
    manager_api.patch(milestone_url(m.id), {"is_completed": True})
    assert manager_api.get(milestone_url(m.id)).data["is_overdue"] is False


def test_deadline_window_filter(manager_api, project):
    Milestone.objects.create(project=project, title="Soon", due_date="2026-08-05")
    Milestone.objects.create(project=project, title="Later", due_date="2026-12-01")
    res = manager_api.get(
        reverse("projects:milestone-list"), {"due_before": "2026-09-01", "is_completed": "false"}
    )
    assert [r["title"] for r in res.data["results"]] == ["Soon"]


def test_staff_milestone_scoping_and_read_only(dev_api, dev, project):
    m = Milestone.objects.create(project=project, title="Design", due_date="2026-08-15")
    # Not a member: the milestone is invisible.
    assert dev_api.get(milestone_url(m.id)).status_code == 404
    ProjectMembership.objects.create(project=project, user=dev, role="developer")
    assert dev_api.get(milestone_url(m.id)).status_code == 200
    # Member, but still read-only (matrix: staff don't edit projects).
    assert dev_api.patch(milestone_url(m.id), {"is_completed": True}).status_code == 403


# ------------------------------------------- history, notes & files wiring


def test_activity_timeline_endpoint(manager_api, project):
    manager_api.patch(reverse("projects:project-detail", args=[project.id]), {"status": "on_hold"})
    res = manager_api.get(
        reverse("activities:activity-list"),
        {"content_type": "project", "object_id": project.id},
    )
    assert res.status_code == 200
    verbs = [r["verb"] for r in res.data["results"]]
    assert "status_changed" in verbs
    assert res.data["results"][0]["target"] == {
        "content_type": "project",
        "object_id": project.id,
    }


def test_notes_attach_to_projects_with_scoping(dev_api, dev, project):
    url = reverse("activities:note-list")
    body = {"body": "Standup notes", "content_type": "project", "object_id": project.id}
    # Not a member → the project "does not exist" for this user.
    assert dev_api.post(url, body).status_code == 400
    ProjectMembership.objects.create(project=project, user=dev, role="developer")
    assert dev_api.post(url, body).status_code == 201
