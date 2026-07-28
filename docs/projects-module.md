# Project Management Module (Phase 4, slice 1)

Backend for projects, teams, milestones, technology tags, plus the project
wiring of files (documents), comments (notes) and history (activities).
Tasks & time entries are the next slice.

## Concepts

- **Project** — a delivery engagement for a client. Soft-deleted (`is_active`)
  because it accumulates audit data (milestones, files, history, later invoices).
- **ProjectMembership** — the through table of the `Project ↔ User` M2M.
  Roles on the project: `manager` (runs it) / `developer` (delivers it).
  This is a *project-level* role, independent of the *global* `User.role`.
- **Milestone** — a dated checkpoint. `completed_at` is service-managed;
  **progress % = completed / total milestones**, computed in SQL annotations,
  never stored. `progress` is `null` when a project has no milestones
  ("nothing planned" ≠ "0% done").
- **Technology** — a real table (tags grow at runtime), attached via plain M2M.
- **Activity** — append-only history rows (`created`, `status_changed`,
  `member_added`, `milestone_completed`, …) written only by
  `apps/activities/services.record()` from inside business services. No write API.

## Permission matrix (§8)

| | ADMIN / MANAGER | STAFF |
|---|---|---|
| See projects | all | **member-of only** (queryset scoping → 404, no leak) |
| Create/edit/delete projects | ✅ | ❌ |
| Manage team & milestones | ✅ | ❌ (read-only) |
| `budget` field | visible | **stripped from the response** |
| Files/notes on a project | ✅ | only on member projects (attachments registry scoping) |

## Endpoints

```
GET/POST      /api/v1/projects/                     ?search= &status= &priority= &client=
                                                    &member= &technology= &due_before=
                                                    &budget_min= &ordering=-end_date
GET/PATCH/DEL /api/v1/projects/{id}/                PATCH only (PUT → 405); DELETE = soft
GET/POST      /api/v1/projects/{id}/members/        add: {user_id, role}
GET/POST      /api/v1/projects/{id}/milestones/     add: {title, description?, due_date}
GET/PATCH/DEL /api/v1/project-memberships/{id}/     manager/admin; PATCH {role}
GET           /api/v1/milestones/                   cross-project deadlines screen:
                                                    ?is_completed=false&due_before=…
GET/PATCH/DEL /api/v1/milestones/{id}/              PATCH {is_completed: true} completes
GET/POST      /api/v1/technologies/                 ?search= ; POST manager/admin
GET           /api/v1/activities/?content_type=project&object_id={id}   history tab
POST          /api/v1/notes/       {content_type: "project", object_id, body}
POST          /api/v1/documents/   multipart, content_type=project, object_id
```

Writes validate with slim serializers but respond with the full detail shape.
Search covers `name`, `description`, `client name`, `technology name`.

## Guards & invariants

- `end_date >= start_date` — serializer 400 + DB `CheckConstraint` backstop.
- Project name unique **per client among live projects** (conditional
  `UniqueConstraint`; soft-deleting frees the name).
- One membership per user per project (constraint + friendly 400).
- **Last-manager guard**: removing or demoting the only `manager` → 400
  (`services.LastManagerError`), same spirit as the last-admin guard on users.
- A project cannot be moved to another client after creation.
- `completed_at` ⇔ `is_completed` kept consistent by `services.save_milestone`,
  which also writes the `milestone_completed` / `milestone_reopened` history row.
- Ordering whitelist excludes `budget` (staff could binary-search the hidden
  value via sort order).
- Counts (`member_count`, `milestone_total/done`) use `Count(..., distinct=True)`
  — multiple JOINs otherwise multiply each other's rows.

## Files touched

- `apps/projects/` — models, serializers, filters, services, views, urls, admin,
  tests (30).
- `apps/activities/` — `Activity` model + `services.record()` + read-only
  `/activities/` endpoint.
- `apps/core/attachments.py` — `project` registered; `get_visible_target()` now
  takes `user` and hides non-member projects from STAFF (documents & notes
  call sites updated).
