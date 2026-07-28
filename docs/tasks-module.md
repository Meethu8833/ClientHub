# Task Management Module (Phase 4, slice 2)

Backend for tasks, dependencies and time tracking inside the `projects` app,
plus the task wiring of files (documents), comments (notes) and history
(activities). Completes Phase 4's backend; the kanban UI is a frontend slice.

## Concepts

- **Task** — one unit of work inside a project. **Hard-deleted** (§4: tasks
  are operational rows, not audit records) — but only via
  `services.delete_task()`, which also removes the notes/documents/activities
  pinned to it (GenericFKs have no DB cascade; skipping this leaves orphans).
- **Lifecycle (`status`)** — `todo → in_progress → review → done`, movable in
  both directions (kanban columns). Invariant, service-enforced:
  `status == done ⇔ completed_at set`; reopening clears it.
- **Priority** — `low/medium/high/urgent`. A separate axis from status
  ("how important" vs "where in the workflow") and a *separate enum* from
  `Project.Priority` on purpose — the two dials must be able to diverge.
- **Assignment** — single `assignee` FK, `SET_NULL` (unassigned = valid
  backlog state). Rule: **the assignee must be a project member**, otherwise
  the task would be invisible to its own assignee under staff scoping.
- **Time tracking** — `TimeEntry` is an append-only *log* (task, user, hours,
  worked_on, description), never a stored total. `Task.estimated_hours` is
  the plan; the actual (`logged_hours`) is `Sum(entries)` computed per query
  via a **subquery** (a joined `Sum` would be inflated by the other joins —
  the multi-annotation trap where `distinct=True` can't save you).
  `user` is `PROTECT`: Phase 8 bills off these rows. Hours per entry:
  `0 < h ≤ 24` (serializer 400 + DB CheckConstraint); no future `worked_on`.
- **Dependencies** — self-referential M2M `blocked_by` (`symmetrical=False`;
  the mirror is `task.blocks`). Rules enforced in the serializer: same
  project, no self-block, **no cycles** (BFS up the blocker graph), and the
  **gate**: a task cannot leave `todo` while any blocker is not `done`
  (400 lists the blocking titles).
- **Comments & files** — no new models: `Note` and `Document` attach via the
  GenericFK registry (`core/attachments.py`, slug `"task"`). Visibility
  follows the project (staff: member projects only; soft-deleted project →
  task invisible).
- **History** — on the task's own timeline: `created`, `status_changed`,
  `assigned` (covers reassign/unassign, `changes` carries from/to), `updated`.
  On the **project's** timeline: `task_deleted` (the task's timeline dies
  with the row, the tombstone must live elsewhere).

## Permission matrix (§8)

| | ADMIN / MANAGER | STAFF |
|---|---|---|
| See tasks | all | member projects only (scoped queryset → 404) |
| Create / delete tasks | ✅ | ❌ |
| Edit tasks | any field | **`status` only, on tasks assigned to them** (else 403) |
| Log time | on any task | on tasks they can see; row is always their own |
| See time entries | all | **own rows only** (nested + flat lists) |
| Edit/delete time entries | anyone's | own only (scoped → foreign rows 404) |

`user` on a time entry always comes from the session, never the body —
nobody pads a colleague's timesheet (or, later, the client's invoice).

## Endpoints

```
GET/POST      /api/v1/projects/{id}/tasks/      create: {title, description?, status?,
                                                priority?, due_date?, estimated_hours?,
                                                assignee_id?, milestone_id?, blocked_by_ids?}
GET           /api/v1/tasks/                    ?project= &status= &priority= &assignee=
                                                &unassigned=true &milestone= &due_before=
                                                &search= &ordering=due_date
GET/PATCH/DEL /api/v1/tasks/{id}/               PATCH same body as create (no PUT);
                                                DELETE manager/admin, cleans attachments
GET/POST      /api/v1/tasks/{id}/time-entries/  log: {hours, worked_on, description?}
GET           /api/v1/time-entries/             report: ?user= &project= &task=
                                                &worked_from= &worked_to=
GET/PATCH/DEL /api/v1/time-entries/{id}/        fix a mislogged row
GET           /api/v1/activities/?content_type=task&object_id={id}   task history
POST          /api/v1/notes/       {content_type: "task", object_id, body}   comments
POST          /api/v1/documents/   multipart, content_type=task, object_id   attachments
```

Reads embed minis (`project/milestone/assignee/blocked_by/blocks`), writes
accept `_id` fields. List rows carry computed `is_overdue`, `logged_hours`,
`open_blockers`; detail adds both sides of the dependency graph. Writes
answer with the full detail shape.

## Guards & invariants

- Milestone/dependencies must belong to the task's project; a task never
  changes project (`project` comes from the URL on create, immutable after).
- Dependency graph is a DAG: self-block and cycles → 400.
- Blocked gate: leaving `todo` with unfinished blockers → 400.
- `completed_at` and all history rows are written only by
  `services.save_task()` — every endpoint routes through it.
- `ChoiceFilter`s 400 on out-of-enum values instead of returning `[]`.

Tests: `apps/projects/tests/test_tasks.py`, `test_time_entries.py` (26).
