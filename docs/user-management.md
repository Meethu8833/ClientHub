# User Management Module

Admin-only API for managing accounts, roles, and lifecycle. Complements the
auth module (`docs/auth-module.md`): auth = "prove who you are", user
management = "administer who exists and what they may do".

Base URL: `/api/v1/users/` — **every** endpoint requires an authenticated
user with `role=admin` (`IsAdmin`), except `PUT/DELETE /api/v1/auth/me/avatar/`
(any logged-in user, own picture only).

## Endpoints

| Method | URL | Purpose |
|---|---|---|
| GET | `/api/v1/users/` | Paginated list. `?search=` (email/first/last name), `?role=`, `?is_active=`, `?joined_after=YYYY-MM-DD`, `?joined_before=`, `?ordering=email\|first_name\|last_name\|role\|date_joined\|last_login` (prefix `-` for desc), `?page=`, `?page_size=` (max 100) |
| POST | `/api/v1/users/` | Create. Body: `email` (required), `first_name`, `last_name`, `role`, `password` (optional). No password → account gets an unusable password and an **invite email** with a set-password link (reuses the reset-password flow). |
| GET | `/api/v1/users/{id}/` | Full detail |
| PATCH | `/api/v1/users/{id}/` | Update `first_name` / `last_name` only (PUT → 405) |
| DELETE | `/api/v1/users/{id}/` | **Soft delete**: sets `deleted_at`, `is_active=False`, revokes refresh tokens. Row is kept; user vanishes from all API queries (404 afterwards). |
| POST | `/api/v1/users/{id}/deactivate/` | Reversible block: `is_active=False` + revoke refresh tokens. Still visible in lists. |
| POST | `/api/v1/users/{id}/activate/` | Re-enable |
| POST | `/api/v1/users/{id}/assign-role/` | Body `{"role": "admin"\|"manager"\|"staff"}` |
| PUT | `/api/v1/users/{id}/avatar/` | Multipart upload, field `avatar`. jpg/jpeg/png/webp, ≤ 2 MB, must decode as a real image (Pillow). Replacing deletes the old file. |
| DELETE | `/api/v1/users/{id}/avatar/` | Remove picture + file |
| PUT/DELETE | `/api/v1/auth/me/avatar/` | Same, for the logged-in user's own picture |

## Guards

- **Self-action** (403): an admin cannot delete, deactivate, or change the
  role of their own account — prevents accidental lockout.
- **Last-admin** (400): the final active admin cannot be deleted, deactivated,
  or demoted. Currently defense-in-depth (the self-guard already blocks the
  reachable path), kept for future permission changes / bulk operations.

## Design decisions

- **Soft delete vs deactivate**: `deleted_at` (permanent, hidden) vs
  `is_active=False` (temporary, visible). Both block login; deactivate is the
  "employee on leave" switch, delete is "left the company". Hard delete is
  impossible anyway once the user owns clients (`on_delete=PROTECT`).
- **Deactivate/delete revoke refresh tokens** — `is_active=False` only stops
  *new* logins; an existing refresh token would keep minting access tokens
  for up to 7 days otherwise.
- **Role changes only via `assign-role`**, not PATCH — a deliberate,
  auditable action with its own guards.
- **Avatar filenames are UUIDs** under `avatars/yyyy/mm/`; the original
  filename is never stored on disk (path-traversal / collision safety).
- **Default manager is unfiltered**; the API filters with
  `User.objects.alive()`. Hiding soft-deleted rows from the default manager
  breaks Django auth internals and FK integrity checks.

## Files

- `apps/accounts/models.py` — `avatar`, `deleted_at`, `UserManager.alive()`
- `apps/accounts/serializers_users.py` — list/detail/create/update/role/avatar serializers
- `apps/accounts/filters.py` — `UserFilter`
- `apps/accounts/services.py` — invite email, deactivate/activate, soft delete, role, avatar
- `apps/accounts/views_users.py` — `UserViewSet`, `MeAvatarView`
- `apps/accounts/urls_users.py` — router, mounted at `/api/v1/`
- `apps/core/pagination.py` — `DefaultPagination` (project-wide)
- `apps/accounts/tests/test_users.py` — 34 tests

## Quick Postman check

1. Login as an admin → copy `access`.
2. `GET /api/v1/users/?search=ana&role=staff&ordering=-date_joined` with
   `Authorization: Bearer <access>`.
3. `POST /api/v1/users/` with `{"email": "new@x.com", "role": "staff"}` →
   201; the invite email prints to the runserver console (dev backend).
4. `PUT /api/v1/users/3/avatar/` → Body → form-data → key `avatar` (type
   File) → pick a PNG → response contains the image URL.
