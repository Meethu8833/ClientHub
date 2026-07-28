# Reports Module

Business reports: parameterized, historical, **exportable** answers to
management questions. Where the dashboard is a glanceable "how are we doing
right now", a report is "give me Q1 revenue by client, as a file I can take
to a meeting". No models, no migrations — like `dashboard`, the `reports`
app owns nothing and aggregates what other apps own.

```
GET /api/v1/reports/revenue/   invoiced / collected / refunded / net   manager+admin
GET /api/v1/reports/time/      logged hours by project or member       all roles
GET /api/v1/reports/tickets/   SLA performance per priority            all roles
```

## Parameters (query string)

Shared by all three, validated by a plain DRF `Serializer` over
`request.query_params` (bad input → 400 before any query runs):

| Param | Default | Notes |
|---|---|---|
| `date_from` | 365 days ago | `YYYY-MM-DD`; range capped at 5 years |
| `date_to` | today | must be ≥ `date_from` |
| `export` | `json` | `json` \| `xlsx` \| `pdf` |

Per report: revenue takes `client`, `group_by=month\|client`; time takes
`project`, `user`, `group_by=project\|user`; tickets takes `client`.
**Not `?format=`** — DRF reserves that name for its own content negotiation.

## The ReportTable contract

Every builder in `services.py` returns the same neutral shape:

```
ReportTable(slug, title, columns=[Column(key, label, kind)], rows, totals, filters)
```

`kind` ∈ `text | int | money | hours` and drives formatting everywhere
downstream: JSON stringifies Decimals (`"1234.50"`), Excel applies a number
format and keeps cells summable, PDF right-aligns. The exporters know *only*
this contract — a new report needs one service function and exports for free;
a new format (CSV, say) needs one exporter and covers every report.

## Windowing semantics

- **Revenue**: invoices by `issue_date` (DRAFT and VOID excluded — one isn't
  a bill yet, the other was retracted), payments by `received_on`
  (COMPLETED only), refunds by `refunded_on`. Invoiced and collected in the
  same bucket deliberately don't reconcile: issue-March/pay-April is real
  timing information. `net = collected − refunded` is cash truth.
  `group_by=client` adds `outstanding` (balance due on the window's
  invoices, computed in SQL like the dashboard).
- **Time**: `TimeEntry.worked_on` — the day the work happened, not the day
  it was typed in.
- **Tickets**: `created_at` cohort. Breached = answered late OR still
  unanswered past the deadline; no deadline stamped → no promise → no
  breach. `avg_resolution_hours` averages `resolved_at − created_at` in SQL
  (Postgres interval arithmetic); the totals row carries `null` there — an
  average of averages would lie.

## Role scoping (§8, same rule as the dashboard)

A report must never show a number the caller couldn't reach by paging the
source endpoint: revenue is `IsManagerOrAdmin` (STAFF get 403, not zeros);
time entries are forced to `user=me` for STAFF even if they pass `?user=`;
the ticket queue is shared.

## Exports

- Excel via **openpyxl**: styled header, freeze panes, per-kind number
  formats, bold totals row, title + filter echo above the table (an exported
  file gets emailed around — it must carry its own context).
- PDF via **reportlab** (platypus): landscape A4, header repeated on every
  page (`repeatRows=1`), zebra rows, numeric columns right-aligned.
- Both are built in memory (`BytesIO`) — reports are aggregated rows, not
  raw tables — and returned with `Content-Disposition: attachment;
  filename="revenue-report-2026-07-28.xlsx"`.

## Security

- **Formula injection**: an Excel cell starting with `=` `+` `-` `@`
  executes as a formula — a client named `=HYPERLINK(...)` would detonate in
  the accountant's spreadsheet. `_safe_text()` prefixes a `'` (Excel's own
  treat-as-text escape); pinned by a test.
- **Markup injection (PDF)**: reportlab `Paragraph`s parse XML-ish tags, so
  all text is XML-escaped first.
- **Resource exhaustion**: the date range is capped at 5 years; parameters
  are validated before any SQL runs.
- **No caching**, deliberately: arbitrary filter combos would mostly cache
  keys nobody reads twice, and a stale export that gets emailed onward is
  worse than a slow one.

## Files

```
apps/reports/
├── serializers.py   query-param validation (defaults, range cap, choices)
├── services.py      ReportTable contract + the three builders (all SQL here)
├── exporters.py     ReportTable → xlsx / pdf attachment (no domain knowledge)
├── views.py         BaseReportView template method: validate → build → render
├── urls.py          three plain paths, no router
└── tests/           aggregation math, scoping per role, 400s, real xlsx/pdf bytes
```
