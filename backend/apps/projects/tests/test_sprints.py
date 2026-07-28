"""
Sprint API tests: the state machine (planned → active → completed, ceremonies
only), the one-active-sprint invariant, completion side effects (snapshots +
backlog return), task↔sprint validation, burndown/velocity read models, and
the permission matrix (manager writes, staff member-scoped reads).
"""

from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.activities.models import Activity
from apps.clients.models import Client
from apps.projects.models import Project, ProjectMembership, Sprint, Task
from apps.projects.services import complete_sprint, start_sprint

PASSWORD = "Str0ng!pass123"

pytestmark = pytest.mark.django_db

LIST_URL = reverse("projects:sprint-list")


def detail_url(sprint_id):
    return reverse("projects:sprint-detail", args=[sprint_id])


def nested_url(project_id):
    return reverse("projects:project-sprints", args=[project_id])


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
def acme():
    return Client.objects.create(name="Acme Fintech", status=Client.Status.ACTIVE)


@pytest.fixture
def project(acme, manager, staff):
    p = Project.objects.create(client=acme, name="Website Redesign", status="in_progress")
    ProjectMembership.objects.create(project=p, user=manager, role="manager")
    ProjectMembership.objects.create(project=p, user=staff, role="developer")
    return p


@pytest.fixture
def other_project(acme, manager):
    # No staff membership — invisible to the staff fixture.
    p = Project.objects.create(client=acme, name="Mobile App")
    ProjectMembership.objects.create(project=p, user=manager, role="manager")
    return p


def make_sprint(project, name="Sprint 1", status=Sprint.Status.PLANNED, days=14):
    return Sprint.objects.create(
        project=project,
        name=name,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1) + timedelta(days=days),
        status=status,
    )


# ------------------------------------------------------------------ create/edit


def test_manager_creates_sprint_nested(manager_api, project):
    resp = manager_api.post(
        nested_url(project.id),
        {
            "name": "Sprint 1",
            "goal": "Ship the checkout flow",
            "start_date": "2026-08-03",
            "end_date": "2026-08-14",
        },
    )
    assert resp.status_code == 201
    assert resp.data["status"] == Sprint.Status.PLANNED
    assert resp.data["project"] == project.id
    assert resp.data["task_count"] == 0
    assert resp.data["points_committed"] == 0
    assert resp.data["total_points"] is None  # snapshot exists only after completion


def test_staff_cannot_create_sprint(staff_api, project):
    resp = staff_api.post(
        nested_url(project.id),
        {"name": "S", "start_date": "2026-08-03", "end_date": "2026-08-14"},
    )
    assert resp.status_code == 403


def test_end_before_start_rejected(manager_api, project):
    resp = manager_api.post(
        nested_url(project.id),
        {"name": "S", "start_date": "2026-08-14", "end_date": "2026-08-03"},
    )
    assert resp.status_code == 400
    assert "end_date" in resp.data


def test_duplicate_name_per_project_rejected(manager_api, project, other_project):
    make_sprint(project, name="Sprint 1")
    resp = manager_api.post(
        nested_url(project.id),
        {"name": "Sprint 1", "start_date": "2026-08-03", "end_date": "2026-08-14"},
    )
    assert resp.status_code == 400
    # …but the same name in ANOTHER project is fine.
    resp = manager_api.post(
        nested_url(other_project.id),
        {"name": "Sprint 1", "start_date": "2026-08-03", "end_date": "2026-08-14"},
    )
    assert resp.status_code == 201


def test_completed_sprint_is_immutable(manager_api, project):
    sprint = make_sprint(project, status=Sprint.Status.COMPLETED)
    resp = manager_api.patch(detail_url(sprint.id), {"goal": "rewrite history"})
    assert resp.status_code == 400


def test_status_not_writable_via_patch(manager_api, project):
    sprint = make_sprint(project)
    resp = manager_api.patch(detail_url(sprint.id), {"status": "active"})
    assert resp.status_code == 200  # unknown field silently ignored (not in write shape)
    sprint.refresh_from_db()
    assert sprint.status == Sprint.Status.PLANNED


# ------------------------------------------------------------------ state machine


def test_start_sprint(manager_api, manager, project):
    sprint = make_sprint(project)
    resp = manager_api.post(detail_url(sprint.id) + "start/")
    assert resp.status_code == 200
    assert resp.data["status"] == Sprint.Status.ACTIVE
    assert resp.data["started_at"] is not None
    assert Activity.objects.filter(verb=Activity.Verb.SPRINT_STARTED).exists()


def test_only_one_active_sprint_per_project(manager_api, project):
    make_sprint(project, name="Running", status=Sprint.Status.ACTIVE)
    sprint = make_sprint(project, name="Next")
    resp = manager_api.post(detail_url(sprint.id) + "start/")
    assert resp.status_code == 400
    assert "active" in str(resp.data["detail"]).lower()


def test_start_requires_planned(manager_api, project):
    sprint = make_sprint(project, status=Sprint.Status.COMPLETED)
    resp = manager_api.post(detail_url(sprint.id) + "start/")
    assert resp.status_code == 400


def test_staff_cannot_run_ceremonies(staff_api, project):
    sprint = make_sprint(project)
    assert staff_api.post(detail_url(sprint.id) + "start/").status_code == 403
    assert staff_api.post(detail_url(sprint.id) + "complete/").status_code == 403


def test_complete_snapshots_and_returns_unfinished_to_backlog(manager_api, manager, project):
    sprint = make_sprint(project, status=Sprint.Status.ACTIVE)
    done = Task.objects.create(
        project=project, title="Done work", sprint=sprint, story_points=5, status=Task.Status.DONE
    )
    open_task = Task.objects.create(
        project=project, title="Unfinished", sprint=sprint, story_points=3
    )

    resp = manager_api.post(detail_url(sprint.id) + "complete/")
    assert resp.status_code == 200
    assert resp.data["status"] == Sprint.Status.COMPLETED
    assert resp.data["total_points"] == 8
    assert resp.data["completed_points"] == 5

    open_task.refresh_from_db()
    done.refresh_from_db()
    assert open_task.sprint_id is None  # back to the backlog
    assert done.sprint_id == sprint.id  # completed work stays for history

    act = Activity.objects.get(verb=Activity.Verb.SPRINT_COMPLETED)
    assert act.changes["completed_points"] == 5
    assert act.changes["returned_to_backlog"] == 1


def test_complete_requires_active(manager_api, project):
    sprint = make_sprint(project)  # still planned
    resp = manager_api.post(detail_url(sprint.id) + "complete/")
    assert resp.status_code == 400


def test_delete_only_planned(manager_api, project):
    active = make_sprint(project, name="Active", status=Sprint.Status.ACTIVE)
    assert manager_api.delete(detail_url(active.id)).status_code == 400

    planned = make_sprint(project, name="Planned")
    task = Task.objects.create(project=project, title="Pulled in early", sprint=planned)
    assert manager_api.delete(detail_url(planned.id)).status_code == 204
    task.refresh_from_db()
    assert task.sprint_id is None  # SET_NULL sent it back to the backlog


# ------------------------------------------------------------------ task ↔ sprint


def test_task_sprint_must_match_project(manager_api, project, other_project):
    foreign = make_sprint(other_project)
    resp = manager_api.post(
        reverse("projects:project-tasks", args=[project.id]),
        {"title": "T", "sprint_id": foreign.id},
    )
    assert resp.status_code == 400
    assert "sprint_id" in resp.data


def test_task_cannot_join_completed_sprint(manager_api, project):
    sprint = make_sprint(project, status=Sprint.Status.COMPLETED)
    resp = manager_api.post(
        reverse("projects:project-tasks", args=[project.id]),
        {"title": "T", "sprint_id": sprint.id},
    )
    assert resp.status_code == 400
    assert "sprint_id" in resp.data


def test_backlog_filter(manager_api, project):
    sprint = make_sprint(project, status=Sprint.Status.ACTIVE)
    Task.objects.create(project=project, title="In sprint", sprint=sprint)
    Task.objects.create(project=project, title="In backlog")
    resp = manager_api.get(reverse("projects:task-list"), {"backlog": "true"})
    assert resp.status_code == 200
    assert [t["title"] for t in resp.data["results"]] == ["In backlog"]


# ------------------------------------------------------------------ scoping


def test_staff_sees_only_member_project_sprints(staff_api, project, other_project):
    make_sprint(project, name="Visible")
    make_sprint(other_project, name="Hidden")
    resp = staff_api.get(LIST_URL)
    assert resp.status_code == 200
    assert [s["name"] for s in resp.data["results"]] == ["Visible"]
    hidden = Sprint.objects.get(name="Hidden")
    assert staff_api.get(detail_url(hidden.id)).status_code == 404  # existence never leaks


# ------------------------------------------------------------------ reports


def test_burndown_shape_and_math(manager_api, manager, project):
    today = timezone.localdate()
    sprint = Sprint.objects.create(
        project=project,
        name="Sprint B",
        start_date=today - timedelta(days=2),
        end_date=today + timedelta(days=2),
        status=Sprint.Status.ACTIVE,
    )
    Task.objects.create(
        project=project,
        title="Finished yesterday",
        sprint=sprint,
        story_points=3,
        status=Task.Status.DONE,
        completed_at=timezone.now() - timedelta(days=1),
    )
    Task.objects.create(project=project, title="Open", sprint=sprint, story_points=5)

    resp = manager_api.get(detail_url(sprint.id) + "burndown/")
    assert resp.status_code == 200
    assert resp.data["total_points"] == 8
    days = resp.data["days"]
    assert len(days) == 5  # inclusive timebox
    assert days[0]["ideal"] == 8 and days[-1]["ideal"] == 0
    by_offset = {i: d for i, d in enumerate(days)}
    assert by_offset[0]["remaining"] == 8  # before anything was done
    assert by_offset[2]["remaining"] == 5  # today: 3 points burned yesterday
    assert by_offset[3]["remaining"] is None  # the future has no actual line


def test_burndown_unavailable_while_planned(manager_api, project):
    sprint = make_sprint(project)
    assert manager_api.get(detail_url(sprint.id) + "burndown/").status_code == 400


def test_velocity_average(manager_api, manager, project):
    # Two sprints completed through the real service so snapshots are frozen.
    for name, points in [("S1", 8), ("S2", 4)]:
        sprint = make_sprint(project, name=name)
        start_sprint(sprint=sprint, actor=manager)
        Task.objects.create(
            project=project,
            title=f"{name} work",
            sprint=sprint,
            story_points=points,
            status=Task.Status.DONE,
        )
        complete_sprint(sprint=sprint, actor=manager)

    resp = manager_api.get(reverse("projects:project-velocity", args=[project.id]))
    assert resp.status_code == 200
    assert resp.data["velocity"] == 6.0  # (8 + 4) / 2
    assert [s["name"] for s in resp.data["sprints"]] == ["S1", "S2"]
