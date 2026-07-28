"""
Task API tests: permission matrix (§8 — manager/admin full; staff member-scoped
reads + status-only writes on OWN tasks), lifecycle invariants (completed_at,
history rows), dependency rules (same project, no self, no cycle, blocked gate),
and GenericFK cleanup on delete.
"""

import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.activities.models import Activity, Note
from apps.clients.models import Client
from apps.projects.models import Milestone, Project, ProjectMembership, Task

PASSWORD = "Str0ng!pass123"

pytestmark = pytest.mark.django_db

LIST_URL = reverse("projects:task-list")


def detail_url(task_id):
    return reverse("projects:task-detail", args=[task_id])


def nested_url(project_id):
    return reverse("projects:project-tasks", args=[project_id])


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


@pytest.fixture
def task(project, staff):
    return Task.objects.create(project=project, title="Build login page", assignee=staff)


def task_activities(task, verb=None):
    qs = Activity.objects.filter(
        content_type=ContentType.objects.get_for_model(Task), object_id=task.pk
    )
    return qs.filter(verb=verb) if verb else qs


# ------------------------------------------------------------- permissions


def test_anonymous_gets_401():
    assert APIClient().get(LIST_URL).status_code == 401


def test_staff_cannot_create_or_delete(staff_api, project, task):
    assert staff_api.post(nested_url(project.id), {"title": "Nope"}).status_code == 403
    assert staff_api.delete(detail_url(task.id)).status_code == 403


def test_staff_sees_only_member_project_tasks(staff_api, task, other_project):
    hidden = Task.objects.create(project=other_project, title="Secret work")

    res = staff_api.get(LIST_URL)
    assert res.status_code == 200
    assert [row["id"] for row in res.data["results"]] == [task.id]
    # Out-of-scope ids 404 (queryset scoping — existence never leaks).
    assert staff_api.get(detail_url(hidden.id)).status_code == 404


def test_staff_can_move_own_task_status(staff_api, task):
    res = staff_api.patch(detail_url(task.id), {"status": "in_progress"})
    assert res.status_code == 200
    assert res.data["status"] == "in_progress"
    assert task_activities(task, Activity.Verb.STATUS_CHANGED).count() == 1


def test_staff_cannot_touch_other_fields_or_others_tasks(staff_api, task, project, manager):
    # Own task, but a non-status field → 403.
    assert staff_api.patch(detail_url(task.id), {"title": "Renamed"}).status_code == 403
    # Visible (member project) but assigned to someone else → 403.
    others = Task.objects.create(project=project, title="Manager's task", assignee=manager)
    assert staff_api.patch(detail_url(others.id), {"status": "done"}).status_code == 403


# --------------------------------------------------------------------- CRUD


def test_manager_creates_task_nested(manager_api, project, staff, manager):
    milestone = Milestone.objects.create(project=project, title="MVP", due_date="2026-09-01")
    res = manager_api.post(
        nested_url(project.id),
        {
            "title": "Build login page",
            "description": "JWT + refresh cookie",
            "priority": "high",
            "due_date": "2026-08-15",
            "estimated_hours": "12.50",
            "assignee_id": staff.id,
            "milestone_id": milestone.id,
        },
    )
    assert res.status_code == 201
    assert res.data["project"]["id"] == project.id
    assert res.data["assignee"]["id"] == staff.id
    assert res.data["milestone"]["id"] == milestone.id
    assert res.data["status"] == "todo"
    assert res.data["logged_hours"] == "0.00"

    task = Task.objects.get(pk=res.data["id"])
    assert task_activities(task, Activity.Verb.CREATED).count() == 1


def test_assignee_must_be_project_member(manager_api, project):
    outsider = User.objects.create_user(
        email="out@example.com", password=PASSWORD, role=User.Role.STAFF
    )
    res = manager_api.post(nested_url(project.id), {"title": "T", "assignee_id": outsider.id})
    assert res.status_code == 400
    assert "assignee_id" in res.data


def test_milestone_must_belong_to_same_project(manager_api, project, other_project):
    foreign = Milestone.objects.create(
        project=other_project, title="Elsewhere", due_date="2026-09-01"
    )
    res = manager_api.post(nested_url(project.id), {"title": "T", "milestone_id": foreign.id})
    assert res.status_code == 400
    assert "milestone_id" in res.data


def test_done_sets_completed_at_and_reopen_clears_it(manager_api, task):
    res = manager_api.patch(detail_url(task.id), {"status": "done"})
    assert res.status_code == 200
    assert res.data["completed_at"] is not None

    res = manager_api.patch(detail_url(task.id), {"status": "in_progress"})
    assert res.data["completed_at"] is None


def test_reassignment_writes_history(manager_api, task, manager):
    res = manager_api.patch(detail_url(task.id), {"assignee_id": manager.id})
    assert res.status_code == 200
    event = task_activities(task, Activity.Verb.ASSIGNED).get()
    assert event.changes["to"]["id"] == manager.id


def test_unassign_is_valid(manager_api, task):
    # format="json": the test client's default multipart encoding can't carry
    # null — real frontends send JSON anyway.
    res = manager_api.patch(detail_url(task.id), {"assignee_id": None}, format="json")
    assert res.status_code == 200
    assert res.data["assignee"] is None


# ------------------------------------------------------------- dependencies


def test_blocked_task_cannot_leave_todo(manager_api, project, task):
    blocker = Task.objects.create(project=project, title="DB migration")
    assert (
        manager_api.patch(detail_url(task.id), {"blocked_by_ids": [blocker.id]}).status_code == 200
    )

    res = manager_api.patch(detail_url(task.id), {"status": "in_progress"})
    assert res.status_code == 400
    assert "DB migration" in res.data["status"][0]

    blocker.status = Task.Status.DONE
    blocker.save()
    assert manager_api.patch(detail_url(task.id), {"status": "in_progress"}).status_code == 200


def test_dependency_must_be_same_project(manager_api, task, other_project):
    foreign = Task.objects.create(project=other_project, title="Elsewhere")
    res = manager_api.patch(detail_url(task.id), {"blocked_by_ids": [foreign.id]})
    assert res.status_code == 400
    assert "blocked_by_ids" in res.data


def test_no_self_block_and_no_cycles(manager_api, project, task):
    assert manager_api.patch(detail_url(task.id), {"blocked_by_ids": [task.id]}).status_code == 400

    # a ← task, then task ← b ← a would close the loop a → task → ... wait:
    # task blocked_by a; a blocked_by b; making b blocked_by task = cycle.
    a = Task.objects.create(project=project, title="A")
    b = Task.objects.create(project=project, title="B")
    task.blocked_by.add(a)
    a.blocked_by.add(b)
    res = manager_api.patch(detail_url(b.id), {"blocked_by_ids": [task.id]})
    assert res.status_code == 400
    assert "cycle" in res.data["blocked_by_ids"][0]


def test_detail_shows_both_sides_of_the_graph(manager_api, project, task):
    blocker = Task.objects.create(project=project, title="DB migration")
    task.blocked_by.add(blocker)

    res = manager_api.get(detail_url(task.id))
    assert [t["id"] for t in res.data["blocked_by"]] == [blocker.id]
    assert res.data["open_blockers"] == 1

    res = manager_api.get(detail_url(blocker.id))
    assert [t["id"] for t in res.data["blocks"]] == [task.id]


# ------------------------------------------------------------------- delete


def test_delete_cleans_generic_fk_orphans(manager_api, manager, project, task):
    note = Note.objects.create(body="On the task", author=manager, content_object=task)
    manager_api.patch(detail_url(task.id), {"status": "in_progress"})  # leaves history

    assert manager_api.delete(detail_url(task.id)).status_code == 204

    assert not Task.objects.filter(pk=task.pk).exists()
    assert not Note.objects.filter(pk=note.pk).exists()
    assert task_activities(task).count() == 0  # no orphaned history rows
    tombstone = Activity.objects.filter(
        content_type=ContentType.objects.get_for_model(Project),
        object_id=project.pk,
        verb=Activity.Verb.TASK_DELETED,
    ).get()
    assert tombstone.changes["title"] == "Build login page"


# --------------------------------------------------------- filters & search


def test_filters_and_search(manager_api, project, other_project, task):
    Task.objects.create(project=project, title="Write docs", status=Task.Status.DONE)
    Task.objects.create(project=other_project, title="Kickoff deck")

    res = manager_api.get(LIST_URL, {"project": project.id, "status": "todo"})
    assert [r["id"] for r in res.data["results"]] == [task.id]

    res = manager_api.get(LIST_URL, {"unassigned": "true"})
    assert {r["title"] for r in res.data["results"]} == {"Write docs", "Kickoff deck"}

    res = manager_api.get(LIST_URL, {"search": "login"})
    assert [r["id"] for r in res.data["results"]] == [task.id]

    # ChoiceFilter rejects out-of-enum values instead of returning [].
    assert manager_api.get(LIST_URL, {"status": "bogus"}).status_code == 400


# -------------------------------------------------------- notes on a task


def test_note_attaches_to_task_with_scoping(manager_api, staff_api, task, other_project):
    payload = {"content_type": "task", "object_id": task.id, "body": "Ship it"}
    assert staff_api.post(reverse("activities:note-list"), payload).status_code == 201

    hidden = Task.objects.create(project=other_project, title="Secret work")
    res = staff_api.post(
        reverse("activities:note-list"),
        {"content_type": "task", "object_id": hidden.id, "body": "?"},
    )
    assert res.status_code == 400  # invisible parent — same 400 as nonexistent

    res = manager_api.get(
        reverse("activities:note-list"), {"content_type": "task", "object_id": task.id}
    )
    assert res.status_code == 200
    assert res.data["count"] == 1
