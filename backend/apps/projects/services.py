"""
Side-effectful business logic for projects (§11: views stay thin; anything
that touches multiple rows or writes history lives here, in a transaction).

Every mutation that matters to an auditor also appends an Activity row —
one service call = one consistent unit of "change + its history".
"""

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.activities.models import Activity, Note
from apps.activities.services import record
from apps.documents.models import Document

from .models import Milestone, Project, ProjectMembership, Sprint, Task


def _user_label(user) -> str:
    return user.get_full_name() or user.email


@transaction.atomic
def create_project(*, project: Project, technologies, actor) -> Project:
    project.save()
    project.technologies.set(technologies)
    record(actor=actor, target=project, verb=Activity.Verb.CREATED, changes={})
    return project


@transaction.atomic
def update_project(*, project: Project, technologies=None, actor) -> Project:
    """
    Persist edits; if the STATUS changed, write a status_changed event (the
    timeline everyone cares about), otherwise a generic updated event.
    """
    old_status = Project.objects.get(pk=project.pk).status
    project.save()
    if technologies is not None:
        project.technologies.set(technologies)

    if project.status != old_status:
        record(
            actor=actor,
            target=project,
            verb=Activity.Verb.STATUS_CHANGED,
            changes={"field": "status", "from": old_status, "to": project.status},
        )
    else:
        record(actor=actor, target=project, verb=Activity.Verb.UPDATED, changes={})
    return project


@transaction.atomic
def soft_delete_project(*, project: Project, actor) -> None:
    """Hide from the API, keep the row — milestones, files and history stay."""
    project.is_active = False
    project.save(update_fields=["is_active", "updated_at"])
    record(actor=actor, target=project, verb=Activity.Verb.DELETED, changes={})


@transaction.atomic
def add_member(*, project: Project, user, role: str, actor) -> ProjectMembership:
    membership = ProjectMembership.objects.create(project=project, user=user, role=role)
    record(
        actor=actor,
        target=project,
        verb=Activity.Verb.MEMBER_ADDED,
        changes={"user_id": user.id, "user": _user_label(user), "role": role},
    )
    return membership


class LastManagerError(Exception):
    """Raised when a change would leave a project with no manager."""


def _is_last_manager(membership: ProjectMembership) -> bool:
    return (
        membership.role == ProjectMembership.Role.MANAGER
        and not membership.project.memberships.filter(role=ProjectMembership.Role.MANAGER)
        .exclude(pk=membership.pk)
        .exists()
    )


@transaction.atomic
def remove_member(*, membership: ProjectMembership, actor) -> None:
    # Same spirit as the users module's last-admin guard: a running project
    # with nobody at the wheel is an operational black hole.
    if _is_last_manager(membership):
        raise LastManagerError("Cannot remove the only manager — assign another manager first.")
    record(
        actor=actor,
        target=membership.project,
        verb=Activity.Verb.MEMBER_REMOVED,
        changes={
            "user_id": membership.user_id,
            "user": _user_label(membership.user),
            "role": membership.role,
        },
    )
    membership.delete()


@transaction.atomic
def change_member_role(*, membership: ProjectMembership, role: str, actor) -> ProjectMembership:
    if membership.role == role:
        return membership  # no-op: no write, no history noise
    if role == ProjectMembership.Role.DEVELOPER and _is_last_manager(membership):
        raise LastManagerError("Cannot demote the only manager — assign another manager first.")
    old_role = membership.role
    membership.role = role
    membership.save(update_fields=["role", "updated_at"])
    record(
        actor=actor,
        target=membership.project,
        verb=Activity.Verb.MEMBER_ROLE_CHANGED,
        changes={
            "user_id": membership.user_id,
            "user": _user_label(membership.user),
            "from": old_role,
            "to": role,
        },
    )
    return membership


@transaction.atomic
def save_milestone(*, milestone: Milestone, actor) -> Milestone:
    """
    Save a milestone, maintaining completed_at and the history trail when the
    completion flag flips (either direction). Routed through here by EVERY
    write path so the invariant "is_completed=True ⇔ completed_at set" holds.
    """
    was_completed = False
    if milestone.pk:
        was_completed = Milestone.objects.get(pk=milestone.pk).is_completed

    if milestone.is_completed and not was_completed:
        milestone.completed_at = timezone.now()
    elif not milestone.is_completed and was_completed:
        milestone.completed_at = None

    milestone.save()

    if milestone.is_completed != was_completed:
        verb = (
            Activity.Verb.MILESTONE_COMPLETED
            if milestone.is_completed
            else Activity.Verb.MILESTONE_REOPENED
        )
        record(
            actor=actor,
            target=milestone.project,
            verb=verb,
            changes={"milestone_id": milestone.pk, "title": milestone.title},
        )
    return milestone


# ------------------------------------------------------------------ sprints


class SprintStateError(Exception):
    """Raised on an illegal sprint transition (the state machine says no)."""


@transaction.atomic
def start_sprint(*, sprint: Sprint, actor) -> Sprint:
    """
    PLANNED → ACTIVE. The friendly checks give a readable 400; the partial
    unique constraint (one_active_sprint_per_project) is the racy-write
    backstop underneath, same layering as everywhere else in this app.
    """
    if sprint.status != Sprint.Status.PLANNED:
        raise SprintStateError("Only a planned sprint can be started.")
    if sprint.project.sprints.filter(status=Sprint.Status.ACTIVE).exists():
        raise SprintStateError("Another sprint is already active — complete it first.")

    sprint.status = Sprint.Status.ACTIVE
    sprint.started_at = timezone.now()
    sprint.save(update_fields=["status", "started_at", "updated_at"])
    record(
        actor=actor,
        target=sprint.project,
        verb=Activity.Verb.SPRINT_STARTED,
        changes={"sprint_id": sprint.pk, "name": sprint.name},
    )
    return sprint


@transaction.atomic
def complete_sprint(*, sprint: Sprint, actor) -> Sprint:
    """
    ACTIVE → COMPLETED, doing the three things Scrum's sprint-end implies,
    atomically (all-or-nothing — a crash mid-way must not leave a sprint
    completed but its totals unsnapshotted):

      1. SNAPSHOT total/completed points onto the sprint — this row is what
         velocity and the historical burndown read forever after;
      2. return unfinished tasks to the BACKLOG (sprint=NULL) — undone work
         is re-planned next sprint, it does not silently roll over;
      3. write the history row with the numbers the retrospective needs.
    """
    if sprint.status != Sprint.Status.ACTIVE:
        raise SprintStateError("Only an active sprint can be completed.")

    tasks = sprint.tasks.all()
    # Coalesce-in-Python: Sum returns None on empty/all-NULL sets.
    total = tasks.aggregate(s=Sum("story_points"))["s"] or 0
    done = tasks.filter(status=Task.Status.DONE)
    completed = done.aggregate(s=Sum("story_points"))["s"] or 0
    returned = tasks.exclude(status=Task.Status.DONE).update(sprint=None)

    sprint.status = Sprint.Status.COMPLETED
    sprint.completed_at = timezone.now()
    sprint.total_points = total
    sprint.completed_points = completed
    sprint.save(
        update_fields=["status", "completed_at", "total_points", "completed_points", "updated_at"]
    )
    record(
        actor=actor,
        target=sprint.project,
        verb=Activity.Verb.SPRINT_COMPLETED,
        changes={
            "sprint_id": sprint.pk,
            "name": sprint.name,
            "completed_points": completed,
            "total_points": total,
            "returned_to_backlog": returned,
        },
    )
    return sprint


# ------------------------------------------------------------------- tasks


def _user_ref(user):
    """{id, name} for history payloads — or None (unassigned is a real state)."""
    return {"id": user.pk, "name": _user_label(user)} if user else None


@transaction.atomic
def save_task(*, task: Task, blocked_by=None, actor) -> Task:
    """
    The single write path for tasks (every endpoint routes here), holding two
    invariants no matter who saved:
      1. status==DONE ⇔ completed_at set (same pattern as save_milestone);
      2. every status/assignee change leaves an Activity row ON THE TASK —
         the contract explicitly says "status changes → Activity row" (§6).
    """
    old = None if task.pk is None else Task.objects.get(pk=task.pk)

    became_done = task.status == Task.Status.DONE and (old is None or old.status != task.status)
    if became_done:
        task.completed_at = timezone.now()
    elif old is not None and task.status != Task.Status.DONE and old.status == Task.Status.DONE:
        task.completed_at = None  # reopened

    task.save()
    if blocked_by is not None:
        task.blocked_by.set(blocked_by)

    if old is None:
        record(
            actor=actor,
            target=task,
            verb=Activity.Verb.CREATED,
            changes={"assignee": _user_ref(task.assignee)} if task.assignee else {},
        )
        return task

    # An edit may change both status and assignee — that is two facts, so two
    # history rows; a generic "updated" row only when nothing notable changed.
    notable = False
    if task.status != old.status:
        notable = True
        record(
            actor=actor,
            target=task,
            verb=Activity.Verb.STATUS_CHANGED,
            changes={"field": "status", "from": old.status, "to": task.status},
        )
    if task.assignee_id != old.assignee_id:
        notable = True
        record(
            actor=actor,
            target=task,
            verb=Activity.Verb.ASSIGNED,
            changes={"from": _user_ref(old.assignee), "to": _user_ref(task.assignee)},
        )
    if not notable:
        record(actor=actor, target=task, verb=Activity.Verb.UPDATED, changes={})
    return task


@transaction.atomic
def delete_task(*, task: Task, actor) -> None:
    """
    Hard delete (§4) — but a GenericFK is just two integer columns, so the
    database CANNOT cascade notes/documents/activities pinned to this task.
    Delete them explicitly or they float forever, pointing at a dead id.
    """
    ct = ContentType.objects.get_for_model(Task)
    Note.objects.filter(content_type=ct, object_id=task.pk).delete()
    for doc in Document.objects.filter(content_type=ct, object_id=task.pk):
        doc.delete()  # one by one so the post_delete file-cleanup signal fires
    Activity.objects.filter(content_type=ct, object_id=task.pk).delete()

    # The task's own timeline just died with it — the tombstone goes on the
    # project so "who deleted what" stays answerable.
    record(
        actor=actor,
        target=task.project,
        verb=Activity.Verb.TASK_DELETED,
        changes={"task_id": task.pk, "title": task.title},
    )
    task.delete()
