# Dashboard Module

Two read-only endpoints that feed the home screen. No models, no migrations —
the `dashboard` app owns nothing; it aggregates what the other apps own.

```
GET /api/v1/dashboard/summary/   KPI tiles   (counts + money, per role)
GET /api/v1/dashboard/charts/    chart datasets (time series + distributions)
```

Both require authentication only — role shapes the *payload*, not access.

## Payload

### `/summary/`

| Block | Contents | Who sees it |
|---|---|---|
| `clients` | total, prospect/active/inactive, new_this_month | everyone (clients are shared reads) |
| `projects` | total, per-status, overdue (end_date past, still running) | STAFF: member projects only |
| `tasks` | open, overdue, my_open, my_due_today, my_overdue | STAFF: member-project tasks; `my_*` always `assignee=me` |
| `tickets` | open, unassigned, escalated, sla_breached, my_open | everyone (shared queue) |
| `quotations` | draft, awaiting_approval, awaiting_client, accepted_this_month, pipeline_value | STAFF: own (`created_by`) only |
| `billing` | draft, awaiting_payment, outstanding/overdue amounts, collected_this_month | **manager/admin only — key absent for STAFF** |
| `as_of` | ISO timestamp of *computation* (survives cache hits truthfully) | everyone |

### `/charts/`

| Dataset | Shape | Who |
|---|---|---|
| `project_status` | `[{status, label, count}]` | everyone (scoped) |
| `tickets_by_month` | 6 months `[{month: "YYYY-MM", opened, resolved}]`, zero-filled | everyone |
| `revenue_by_month` | 12 months `[{month, revenue}]` — completed payments − refunds | manager/admin |
| `invoice_aging` | `{current, days_1_30, days_31_60, days_61_90, days_over_90}` on balance due | manager/admin |

Money is always a **string** (`"800.00"`), same as `/payments/summary/`:
JSON has no Decimal and floats corrupt money. Counts are plain ints.

## Design decisions

- **Scoping = whatever a role can LIST it may COUNT.** Every block reuses the
  visibility rule of its source module (§8). The dashboard must never leak a
  number the user couldn't reach by paging the underlying endpoint — that's
  why STAFF get *no* billing key at all rather than zeros (zeros are still
  information).
- **One query per block** via conditional aggregation:
  `Count("id", filter=Q(...))` compiles to Postgres
  `COUNT(*) FILTER (WHERE ...)` — total/per-status/overdue in a single table
  scan instead of one query per tile. `/summary/` is ~7 queries flat,
  regardless of row counts.
- **Balance due is computed in SQL** (`grand_total − amount_paid +
  amount_refunded` as an `F()` expression), mirroring the Python properties
  on `Invoice`. Properties work on one instance; aggregates need the SQL
  twin. If the balance definition ever changes, change **both** places.
- **Time series group in SQL, zero-fill in Python.** `TruncMonth` +
  `values().annotate()` does GROUP BY month, but GROUP BY only returns months
  that have rows — a chart needs an unbroken axis, so missing months are
  filled with explicit zeros in the service.
- **No serializers.** The payload is computed aggregates, not model
  instances; shape is documented via `extend_schema` and pinned by tests.
  Plain `APIView`s, not ViewSets — no queryset/pagination machinery to carry.

## Caching

- **Low-level cache API** in the shared view base: `cache.get(key)` → miss →
  compute → `cache.set(key, data, 120)`. TTL-only, **no invalidation**: a KPI
  tile that's ≤2 minutes stale is harmless, and event-based invalidation
  would couple every app's write path to the dashboard.
- **Keys carry the scope, versioned:** `dashboard:summary:v1:global` shared
  by admin+manager (identical payloads), `dashboard:summary:v1:user:<id>` per
  STAFF user. Anything that changes the payload must be in the key —
  otherwise one user is served another's numbers. Bump `v1` when the payload
  shape changes; stale entries just stop being read (no flush ceremony).
- **Backends:** dev = LocMem (explicit in `base.py`; per-process, fine for
  runserver). Prod = Django's built-in `RedisCache` when `REDIS_URL` is set
  (`prod.py`; LocMem is wrong under gunicorn — N workers would keep N private
  caches). `redis` client added to `requirements/prod.txt` only.
- `conftest.py` already clears the cache between tests (was added for
  throttling) — dashboard tests inherit that isolation for free.

## Extending

To add a KPI: add a `Count(..., filter=Q(...))` to the right block in
`apps/dashboard/services.py` (or a new `_xxx_block()` wired into
`get_summary`), respect the source module's scoping, return money via
`_money()`, and pin the number in `tests/test_dashboard.py`. If the payload
shape changes, bump the `v1` in `views._cache_key`.

Deliberately not included: meetings/notifications widgets (their screens are
their own dashboards), per-user leaderboards (people-analytics is a policy
decision, not a default), and long-window caching (dashboards must feel
live-ish; 120 s is the ceiling chosen).
