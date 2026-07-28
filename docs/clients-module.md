# Client Management Module (Phase 2 backend)

Covers three apps: `clients` (Client + Contact), `documents` (file attachments,
pulled forward from Phase 5), `activities` (Notes, pulled forward from Phase 5).

## Permission summary (ARCHITECTURE.md §8)

| Action | ADMIN | MANAGER | STAFF |
|---|---|---|---|
| Read clients/contacts | ✅ | ✅ | ✅ |
| Create/update/delete clients/contacts | ✅ | ✅ | ❌ 403 |
| Upload / view / download documents, write notes | ✅ | ✅ | ✅ |
| Delete documents / edit-delete notes | any | any | own only |

## Endpoints

### Clients

| Method + URL | Body | Success | Notes |
|---|---|---|---|
| `GET /api/v1/clients/` | — | 200 paginated | `?search=` (name/email/phone/GSTIN/city/industry), `?status=`, `?industry=`, `?city=`, `?account_manager=`, `?created_after/before=`, `?ordering=name\|status\|created_at\|updated_at` |
| `GET /api/v1/clients/check/` | — | 200 `{name_taken?, gst_number_taken?}` | instant duplicate pre-check for the form: `?name=` (case-insensitive), `?gst_number=` (normalized), `?exclude={id}` on edit. Sees soft-deleted rows (the unique constraints do too). Advisory — write validation still enforces |
| `POST /api/v1/clients/` | client fields | 201 detail shape | manager/admin |
| `GET /api/v1/clients/{id}/` | — | 200 detail + contacts | |
| `PATCH /api/v1/clients/{id}/` | changed fields | 200 detail | PUT → 405 |
| `DELETE /api/v1/clients/{id}/` | — | 204 | SOFT delete (`is_active=False`), then 404 everywhere |
| `GET /api/v1/clients/{id}/contacts/` | — | 200 paginated | |
| `POST /api/v1/clients/{id}/contacts/` | contact fields | 201 | client comes from URL |

Client write fields: `name`* (unique), `industry`, `website`, `email`,
`phone` (optional — validated `^\+?[0-9](?:[ \-()]{0,2}[0-9]){6,14}$`: optional `+`,
7–15 digits, space/dash/bracket separators; same rule on `Contact.phone`; the form
edits it as a country-driven dial-code prefix + number),
`gst_number` (optional GSTIN — validated `^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$`,
normalized to uppercase, unique when set), `address_line1/2`, `city`, `state`,
`postal_code`, `country` (default "India"), `status` (`prospect`|`active`|`inactive`,
default `prospect`), `account_manager_id` (nullable; must be a non-deleted user).

### Contacts (flat writes)

| Method + URL | Notes |
|---|---|
| `GET /api/v1/contacts/{id}/` | 404 if the parent client is soft-deleted |
| `PATCH /api/v1/contacts/{id}/` | fields: name, email, phone, position, is_primary. Setting `is_primary=true` atomically demotes the previous primary (DB constraint guarantees ≤1 per client) |
| `DELETE /api/v1/contacts/{id}/` | hard delete (§4: operational rows) |

### Documents

| Method + URL | Notes |
|---|---|
| `POST /api/v1/documents/` | multipart: `file`, `content_type=client`, `object_id`. Gates: ≤20 MB → extension whitelist (pdf docx xlsx csv png jpg jpeg zip) → libmagic byte-sniff must match extension. Stored as `documents/yyyy/mm/<uuid>.<ext>`; sniffed MIME recorded, client header ignored |
| `GET /api/v1/documents/?content_type=client&object_id=7` | params mandatory — no global dump |
| `GET /api/v1/documents/{id}/download/` | auth-checked; dev = FileResponse, prod = `X-Accel-Redirect` when `DOCUMENT_X_ACCEL_PREFIX` env var is set (matching `internal;` Nginx location required, Phase 7) |
| `DELETE /api/v1/documents/{id}/` | staff own-only; post_delete signal removes the file from storage |

No update endpoint by design: replace = upload new + delete old.

### Notes

| Method + URL | Notes |
|---|---|
| `POST /api/v1/notes/` | `{body, content_type: "client", object_id}` |
| `GET /api/v1/notes/?content_type=client&object_id=7` | params mandatory |
| `PATCH /api/v1/notes/{id}/` | body only — a note can never be re-pinned to another object; author or manager/admin |
| `DELETE /api/v1/notes/{id}/` | author or manager/admin |

## Design decisions

- **Address embedded on Client, not a table** — exactly one address per client
  today; promote to a 1→N `Address` model only when billing/shipping split.
- **GenericFK whitelist** — `apps/core/attachments.py` `ATTACHABLE_MODELS`
  maps public slugs → models (`"client"` now; add `"project"`, `"task"`,
  `"deal"` there as those apps land). Both documents and notes validate
  targets through it, including invisibility of soft-deleted parents.
- **Soft delete = `is_active` flag** (per §4 ERD) — unlike `User.deleted_at`;
  querysets filter `is_active=True` so dead clients 404 consistently, and
  their contacts/documents/notes become unreachable too.
- **`python-magic` added to requirements/base.txt** (needs system `libmagic`,
  present on Debian/Ubuntu via the `file` package).

## Testing

43 new tests (`apps/clients/tests/`, `apps/documents/tests/`,
`apps/activities/tests/`). Full suite: `.venv/bin/python -m pytest -q` → 99 passed.
