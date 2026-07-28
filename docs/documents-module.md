# Document Management Module

Files attached to business objects (clients, projects, tasks, tickets, quotations,
invoices), with **version history**, **private downloads**, a **swappable storage
backend** (local disk ⇄ S3), and an **orphan-file sweep**. Implements and extends
ARCHITECTURE.md §9.

This doc first explains the concepts (storage, static vs media, S3, versioning,
permissions, security), then documents the implementation and API.

---

## 1. Concepts

### 1.1 Static files vs media files

Django has **two completely separate file systems**, and mixing them up is the
classic beginner mistake:

| | Static files | Media files |
|---|---|---|
| What | Files **you** ship: CSS, JS, admin assets | Files **users** upload: PDFs, avatars |
| Known at deploy time? | Yes — part of the codebase | No — created at runtime |
| Settings | `STATIC_URL`, `STATIC_ROOT` | `MEDIA_URL`, `MEDIA_ROOT` |
| Prod handling | `collectstatic` → served publicly by Nginx | **Never public** in ClientHub |
| Trust level | Trusted (you wrote them) | **Untrusted** (anyone can upload anything) |

`collectstatic` copies every app's static assets into `STATIC_ROOT` so one Nginx
`location /static/` can serve them with far-future cache headers. Static files are
public by definition.

Media is the opposite: a client's signed contract must **never** be reachable at a
guessable public URL. That single difference drives most of this module's design.

### 1.2 The storage abstraction

Application code never touches the filesystem directly. `FileField` delegates every
read/write/delete/url operation to a **storage backend** — a class with a small
interface (`save`, `open`, `delete`, `exists`, `url`, `listdir`…). Which class is
used comes from the `STORAGES` setting (Django 4.2+):

```python
# config/settings/base.py — the explicit default
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
```

Because models, serializers, signals, and the sweep command all go through this
interface, **swapping local disk for S3 is a settings change, zero code changes**.
That is the whole point of the abstraction — and why you should never write
`open(settings.MEDIA_ROOT / ...)` in app code.

### 1.3 Local storage (dev, and small prod)

`FileSystemStorage` writes under `MEDIA_ROOT` (`backend/media/`, gitignored).

- **Dev:** the `download` endpoint streams the file through Django (`FileResponse`).
  Fine for one developer; wasteful in prod because a Python worker is pinned for the
  whole transfer.
- **Prod (single server):** files live on a Docker volume; Django still does the
  auth, but hands the actual byte-pushing to Nginx via **`X-Accel-Redirect`**: the
  view returns an empty response with a header pointing into an `internal;` Nginx
  location. Nginx (C, sendfile) streams the bytes; the location is unreachable
  directly from the internet. Enabled by setting `DOCUMENT_X_ACCEL_PREFIX`.

Limits of local storage: one machine's disk, no redundancy beyond your backups,
and it breaks the moment you run two app servers (uploads land on one machine,
downloads hit the other).

### 1.4 AWS S3 (and S3-compatibles)

**Object storage**: an HTTP API over (bucket, key) → bytes, with 11-nines
durability, unlimited capacity, and no server to run. `django-storages` provides
`S3Storage`, which implements the same storage interface on top of `boto3`.

Enabled in prod with `USE_S3=True` ([prod.py](../backend/config/settings/prod.py)):

- `default_acl="private"` + `querystring_auth=True` — the bucket is **private**.
  A file's "URL" is a **presigned URL**: the object key plus an HMAC signature and
  expiry generated with the server's credentials. Anyone holding the URL can fetch
  the object *until it expires* (`querystring_expire=300` → 5 minutes). This is the
  S3 equivalent of X-Accel: Django does the permission check, then delegates the
  byte-streaming — to AWS instead of Nginx. The download endpoint answers with a
  **302 redirect** to the presigned URL.
- Credentials: prefer an **IAM role** on the EC2/ECS instance (leave
  `AWS_ACCESS_KEY_ID` empty and boto3 finds the role automatically) over static
  keys in `.env`. If you must use keys, scope them to this bucket only.
- `endpoint_url` supports S3-compatibles (MinIO, DigitalOcean Spaces, Cloudflare
  R2) — useful for a self-hosted MinIO in docker-compose to test the S3 path
  locally.
- `file_overwrite=False`: on a name collision S3Storage would otherwise silently
  replace the object. Our UUID names make collisions near-impossible; this is
  defense in depth.

**When to switch:** more than one app server, media outgrowing the disk, or
wanting durability you don't have to manage. Not before — local + Nginx is
simpler and free.

### 1.5 Versioning — why and which design

"Please replace the contract with the signed copy" is a real workflow. Overwriting
the file would **destroy evidence** — you could never prove what the client saw
before signing. So a replacement is an *append*, never an *overwrite*.

Three common designs:

1. **Overwrite in place** — simplest, loses history. Rejected.
2. **Self-referencing rows** — each new upload is a new `Document` pointing at the
   one it supersedes (this is how `quotations` does revisions, because each
   quotation revision is itself a full business object with its own status).
3. **Two-model split** — `Document` (the logical identity) + `DocumentVersion`
   (one physical file per row). The document keeps a stable id — links, notes and
   activity history keep pointing at the same record while its content evolves.
   This is how Google Drive/SharePoint model it, and what we built:

```
Document            "Contract with Acme"  → attached to client 7, stable id 42
 ├─ Version 1       contract_draft.pdf    (2026-07-01)
 ├─ Version 2       contract_v2.pdf       (2026-07-15)
 └─ Version 3  ◄──  contract_signed.pdf   (current_version pointer)
```

`current_version` is a **denormalized pointer** (same trick as the denormalized
totals on quotations/invoices): list screens read one FK instead of sorting
version rows. It is maintained only by `services.py`, inside a transaction.

**Race safety:** two simultaneous uploads would both read "latest = 2" and both
write version 3. `services.add_version` takes a `select_for_update` row lock on
the document (same pattern as invoice numbering), and a DB `UniqueConstraint
(document, version_number)` is the backstop.

### 1.6 Permissions

Layered like the rest of ClientHub (§8):

| Action | Rule |
|---|---|
| Upload / view / download | Any authenticated role — **on objects they can see** |
| Add a new version | Uploader themself, or manager/admin (`IsOwnerOrManager`) |
| Delete a document | Uploader themself, or manager/admin |

Two subtleties:

- **Visibility is inherited from the parent object**, enforced by
  `apps.core.attachments.get_visible_target`: staff can't attach to (or list
  documents of) projects they're not members of, quotations they didn't create, or
  invoices at all. Out-of-scope targets answer exactly like missing ones ("no such
  object") so the API doesn't leak which ids exist.
- **Re-versioning is guarded like delete, not like upload**: appending a version
  changes what the document *is* (the current file everyone downloads), so staff
  may only re-version their own documents. History still protects against abuse —
  nothing is destroyed — but the guard keeps ownership meaningful.

### 1.7 File security (the threat model)

Uploads are attacker-controlled input. The defenses, in order:

1. **Size cap** (20 MB serializer-side; `client_max_body_size` in Nginx rejects
   even earlier so a 5 GB body never reaches Python).
2. **Extension whitelist** — pdf, docx, xlsx, csv, png, jpg, zip. No executables;
   **no SVG** (SVGs can embed `<script>` and execute in the browser = stored XSS).
3. **Byte sniffing** (python-magic/libmagic): the file's *magic numbers* must agree
   with its extension. `virus.exe` renamed `report.pdf` dies here. The sniffed MIME
   is what we store and serve — the client's `Content-Type` header is never trusted.
4. **UUID storage names** — the user's filename never touches the filesystem, so
   `../../etc/cron.d/evil` path traversal and collisions are impossible. The real
   name lives in `Document.original_name` (display + Content-Disposition only).
5. **Private media** — no public `/media/` URL, ever. Every download passes
   authentication + object permission first, then streams via FileResponse /
   X-Accel / presigned URL.
6. **Mandatory list scoping** — `GET /documents/` without `?content_type=&object_id=`
   is a 400; a global "all files" dump is never a real screen and would bypass
   per-object visibility.

All three upload gates run server-side and are shared by both upload endpoints
(`run_upload_gates` in [serializers.py](../backend/apps/documents/serializers.py)).
Frontend checks are UX sugar only — anything can be sent with curl.

---

## 2. Implementation

### 2.1 Models ([models.py](../backend/apps/documents/models.py))

**`Document`** — the logical record: `original_name`, `uploaded_by` (SET_NULL —
deleting a user must not destroy client files), the GenericFK trio
(`content_type` + `object_id` + `content_object`), and `current_version`
(SET_NULL, service-maintained). Composite index on
`(content_type, object_id, -created_at)` — *the* query of this table.

**`DocumentVersion`** — one physical file: `document` (CASCADE), `version_number`
(unique per document), `file` (UUID path `documents/yyyy/mm/<uuid>.<ext>`),
`mime_type` + `size_bytes` (captured at upload so lists never touch storage),
`uploaded_by`. Append-only.

Migration [0002](../backend/apps/documents/migrations/0002_document_versioning.py)
is **hand-ordered**: create table → copy each document's file into a version-1 row
(preserving timestamps) → point `current_version` → *then* drop the old columns.
The auto-generated migration dropped the columns first, which would have destroyed
every stored file path — the reason migrations are reviewed like code (§11).

### 2.2 Services ([services.py](../backend/apps/documents/services.py))

- `create_document(target, file, mime_type, user)` — document + version 1, atomic.
- `add_version(document, file, mime_type, user)` — `select_for_update` lock,
  next number, promote to current, atomic.

### 2.3 Signals, sweep, admin

- [signals.py](../backend/apps/documents/signals.py): `post_delete` on
  **DocumentVersion** deletes the physical file. Document deletion cascades through
  the ORM collector, which fires the signal once per version — one DELETE cleans up
  every historical file. `post_delete` (not `pre_`) so a rolled-back transaction
  never destroys a file whose row survived.
- `python manage.py sweep_orphan_files [--dry-run] [--min-age-hours N]` — nightly
  cron. Walks the default storage under `documents/` (works on disk *and* S3),
  deletes files no `DocumentVersion` references. The 24 h age guard exists because
  Django writes the file *before* the DB row commits — a brand-new file can look
  orphaned for a moment.
- Admin: read-only version inline; versions are never hand-edited.

### 2.4 API

Base: `/api/v1/documents/` (JWT required throughout).

| Method & path | What | Who |
|---|---|---|
| `POST /documents/` | Upload: multipart `file`, `content_type` (slug), `object_id` → 201 document shape | any role, visible targets |
| `GET /documents/?content_type=client&object_id=7` | List for one object (paginated) | any role, visible targets |
| `GET /documents/{id}/` | Metadata (current version) | any role |
| `GET /documents/{id}/versions/` | History, newest first | any role |
| `POST /documents/{id}/versions/` | Multipart `file` → 201 version shape, becomes current | owner or manager+ |
| `GET /documents/{id}/download/` | The bytes (`?version=N` for older; bad param → 400, unknown version → 404) | any role |
| `DELETE /documents/{id}/` | Remove document + **all** versions + files | owner or manager+ |

Document read shape:

```json
{
  "id": 42,
  "original_name": "contract.pdf",
  "mime_type": "application/pdf",
  "size_bytes": 18344,
  "version": 3,
  "versions_count": 3,
  "uploaded_by": {"id": 5, "name": "Priya Nair"},
  "target": {"content_type": "client", "object_id": 7},
  "download_url": "/api/v1/documents/42/download/",
  "created_at": "…", "updated_at": "…"
}
```

No PATCH anywhere: a version is immutable evidence; "replace" = append a version.

### 2.5 Download flow by environment

| Environment | Config | Mechanism |
|---|---|---|
| Dev | (nothing) | Django `FileResponse` streams the file |
| Prod, local volume | `DOCUMENT_X_ACCEL_PREFIX=/internal-media/` + `internal;` Nginx location | `X-Accel-Redirect`: auth in Python, bytes in C |
| Prod, S3 | `USE_S3=True` + bucket vars | 302 → presigned URL (5-min expiry), `ResponseContentDisposition` restores the real filename |

The view picks the branch by inspecting the storage class — no per-environment code.

### 2.6 Configuration reference

`.env` (see `.env.example`): `DOCUMENT_X_ACCEL_PREFIX`, `USE_S3`,
`AWS_STORAGE_BUCKET_NAME`, `AWS_S3_REGION_NAME`, `AWS_S3_ENDPOINT_URL`,
`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` (empty on AWS = IAM role).
`django-storages[s3]` is a **prod-only** dependency (`requirements/prod.txt`).

### 2.7 Tests

`apps/documents/tests/test_documents.py` — the three gates, target validation,
scoped listing, download (current + `?version=`), delete rules with file cleanup
across all versions, version permissions (staff ≠ owner → 403), history ordering,
and the sweep command (orphan deleted / referenced kept / dry-run / age guard).

---

## 3. Beginner pitfalls this module dodges

- Trusting the client's `Content-Type` header (we store the **sniffed** MIME).
- Serving `/media/` publicly in prod (one `location /media/` in Nginx and every
  contract is world-readable).
- Using the uploaded filename on disk (path traversal, collisions, encoding bugs).
- Allowing SVG "images" (stored XSS).
- Deleting DB rows and leaving files forever (signal + sweep).
- Overwriting files on "replace" (destroys evidence; versioning appends).
- Version numbering without a lock (duplicate version 3 under concurrency).
- Writing `open(MEDIA_ROOT / name)` in app code (breaks the moment S3 is enabled).
