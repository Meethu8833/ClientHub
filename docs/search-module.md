# Global Search Module

One endpoint that searches clients, contacts, projects, tasks, tickets,
quotations, invoices and users in a single call, grouped by type, scoped by
role. Backed by two Postgres index technologies chosen per field shape.

- App: `apps/search` (no models — like `dashboard`, it only reads)
- Endpoint: `GET /api/v1/search/?q=<term>[&types=a,b][&limit=5]`
- Tests: `apps/search/tests/test_search.py` (16)

---

## 1. The concepts, from the ground up

### 1.1 SQL LIKE — and why `%term%` is the slow one

`LIKE` is SQL's pattern match. `%` means "anything here":

```sql
SELECT * FROM clients_client WHERE name LIKE 'Acme%';   -- prefix
SELECT * FROM clients_client WHERE name LIKE '%acme%';  -- contains
```

Django's `name__icontains="acme"` compiles (on Postgres) to:

```sql
WHERE UPPER(name) LIKE UPPER('%acme%')
```

Note two things it did for you: case-insensitivity via `UPPER(...)` on **both**
sides, and — critically — **escaping**. Never build LIKE patterns by string
concatenation; a user typing `%` or `_` would change the query's meaning
(and concatenating raw input into SQL is how SQL injection happens). The ORM
parameterizes everything.

**The performance problem.** A normal index is a B-tree: values stored in
sorted order, like a phone book. A phone book finds "Sharma, …" instantly
(known prefix) but is useless for "everyone whose name *contains* 'arm'" —
you'd read every page. Same for the database:

| Pattern | B-tree usable? |
|---|---|
| `LIKE 'Acme%'` (prefix) | yes* |
| `LIKE '%Ltd'` (suffix) | no |
| `LIKE '%acme%'` (contains) | **no — full table scan** |

\* with the right operator class, and only on the raw column — wrap it in
`UPPER()` and even this stops working unless the index is on `UPPER(name)`.

At 500 rows nobody notices a scan. At 500k rows every keystroke in a search
box scans half a gigabyte. Two escape routes exist, and we use both.

### 1.2 Trigram indexes — making `%term%` fast

The `pg_trgm` extension chops text into every overlapping 3-letter window:

```
"acme"  →  {"  a", " ac", "acm", "cme", "me "}
```

A **GIN index** (Generalized Inverted iNdex — the same structure as a book's
back-of-book index) maps each trigram → the rows containing it. To answer
`%acme%`, Postgres intersects the row-lists for "acm" and "cme": index work,
not a scan. This is exactly how the search box on GitHub-scale apps stays
fast for *substring* queries, and it also enables fuzzy matching
(`similarity()`) for typos — a future upgrade we get for free.

**The trap we hit (for real, during this build):** an index accelerates a
query only if the indexed *expression* matches the query's expression.
`icontains` queries `UPPER(name)`; our first index was on plain `name` —
`EXPLAIN` showed the index was **never used**. The fix:

```python
GinIndex(OpClass(Upper("name"), name="gin_trgm_ops"), name="client_name_trgm")
```

Rule to remember: **an index is a bet on a specific query shape; only
`EXPLAIN` tells you the bet paid off.**

### 1.3 Full-text search — matching *words*, not substrings

LIKE/trigram match *characters*. Prose needs *word* semantics: searching
"deploying" should find a ticket that says "we **deployed** the release".
Postgres FTS does three things at write/match time:

1. **Tokenize** — split text into words.
2. **Normalize (stem)** — "deploying", "deployed", "deploys" → `deploy`;
   stop-words ("the", "we", "a") are dropped entirely.
3. **Store as `tsvector`** — a sorted list of stems with positions; the
   query side becomes a `tsquery`, and `@@` tests the match.

```sql
to_tsvector('english', 'we deployed the release')  -- 'deploy':2 'releas':4
       @@ plainto_tsquery('english', 'deploying')  -- true
```

The `'english'` **config** picks the stemmer/stop-word list. It must be
identical on index and query or they don't line up — we pin it once as
`FTS_CONFIG` in `apps/search/services.py`.

**Ranking.** FTS can also say *how well* a row matches (`ts_rank`): more
hits, closer together, rank higher. Django exposes this as `SearchRank`;
we `order_by("-rank")` so the best match is first — something LIKE
fundamentally cannot do (a row either LIKEs or it doesn't).

**What FTS cannot do:** partial words. "epor" is not a stem, so FTS will
never find "report" with it. That's why prose models get **both** strategies
OR-ed together (see §3).

### 1.4 The three ways to index FTS, and which we chose

| Approach | How | Trade-off |
|---|---|---|
| None (compute per query) | `annotate(search=SearchVector(...))` | `to_tsvector` runs on **every row, every query** — fine for a demo, dies at scale |
| **Expression index** *(chosen)* | `GinIndex(SearchVector(...), name=...)` in `Meta.indexes` | Zero extra columns/moving parts; index used only when the query repeats the exact expression |
| Stored `SearchVectorField` + trigger | Materialized `tsvector` column kept fresh by a DB trigger | Fastest reads, no expression-matching footgun — but a new column on every table + trigger machinery. The upgrade path when tables reach millions of rows |

`EXPLAIN` verified our expression indexes hit
(`Bitmap Index Scan on ticket_fts`).

### 1.5 Query optimization — the working checklist

- **`EXPLAIN` is the only truth.** `EXPLAIN ANALYZE <sql>` shows scan type
  and real timing. Dev tables are tiny, so the planner *correctly* seq-scans
  them (reading 10 rows beats opening an index); `SET enable_seqscan = off`
  forces it to reveal whether the index *could* serve the query. That's how
  we caught the dead trigram index.
- **`LIMIT` everything.** Every search type fetches at most `limit+1` rows.
- **Don't COUNT what you won't show.** `COUNT(*)` over an ILIKE match costs
  the same as scanning all matches. We fetch `limit+1` and report `has_more`
  instead of a total.
- **Kill N+1s.** Every result subtitle that reads a relation
  (`project.client.name`) uses `select_related` — 1 JOIN, not N queries.
- **`DISTINCT` when JOINs multiply.** Staff scoping joins `memberships`; a
  project with 2 memberships would appear twice without `.distinct()`.
- **One query per type, ~8 max per request** — a bounded, predictable cost.

### 1.6 Performance & security decisions in this module

- **Min query length 2** — `%a%` matches half the DB for garbage value, and
  trigram indexes need ≥3 chars to bite properly.
- **`limit` clamped 1–20** — the server owns its worst case, not the caller.
- **Not cached** — unlike the dashboard (many users, same question), search
  keys are near-unique per keystroke: all memory cost, ~0 hit rate.
- **Visibility = each module's LIST rule (§8).** Staff: member projects/
  tasks, own quotations, no invoices, no users. Forbidden types are
  **absent keys**, not empty lists — an empty `invoices: []` would leak to
  staff that invoices are searchable (dashboard's billing-blackout rule).
- **Soft-deleted rows never surface** (`is_active` / `deleted_at` filters —
  same querysets as the list endpoints).
- **Frontend etiquette** (when we build it): debounce ~300 ms and cancel
  stale requests, or every keystroke becomes 8 queries.

---

## 2. API

`GET /api/v1/search/?q=phoenix&types=clients,projects&limit=5`
(any authenticated user)

| Param | Rules |
|---|---|
| `q` | required, ≥2 chars after trim → else 400 |
| `types` | optional CSV subset of `clients, contacts, projects, tasks, tickets, quotations, invoices, users`; unknown name → 400 |
| `limit` | per-type cap, clamped 1–20, default 5; non-integer → 400 |

```json
{
  "query": "phoenix",
  "limit": 5,
  "results": {
    "clients":  { "items": [ { "type": "client", "id": 7,
                               "title": "Acme Phoenix Ltd",
                               "subtitle": "active · Pune" } ],
                  "has_more": false },
    "projects": { "items": [ ... ], "has_more": true }
  }
}
```

Every hit has the same four keys (`type`, `id`, `title`, `subtitle`) so the
frontend renders one flat component for all eight types.

**Who sees which type** — the §8 LIST column, verbatim:

| Type | admin | manager | staff |
|---|---|---|---|
| clients, contacts, tickets | ✓ | ✓ | ✓ (all rows) |
| projects, tasks | ✓ | ✓ | member projects only |
| quotations | ✓ | ✓ | own (`created_by`) only |
| invoices | ✓ | ✓ | **key absent** |
| users | ✓ | key absent | key absent |

**Match strategy per type:**

| Type | Strategy | Fields |
|---|---|---|
| clients | substring | name, email, gst_number |
| contacts | substring | name, email |
| projects | FTS + substring, rank-ordered | name+description / name |
| tasks | FTS + substring, rank-ordered | title+description / title |
| tickets | FTS + substring, rank-ordered | subject+description / subject |
| quotations | substring | title, quote_number |
| invoices | substring | invoice_number, client name |
| users | substring | first/last name, email |

---

## 3. Implementation map

| Piece | Where |
|---|---|
| pg_trgm extension | `apps/search/migrations/0001_enable_pg_trgm.py` — model-less migration every trigram-index migration depends on (extension must exist first; hand-added dependency) |
| Trigram GIN indexes | `Meta.indexes` of Client, Contact, Project, Task, Ticket, Quotation, Invoice — always `OpClass(Upper(field), "gin_trgm_ops")` |
| FTS expression GIN indexes | Project, Task, Ticket — `GinIndex(SearchVector(..., config="english"))`; the query in services repeats the expression byte-for-byte |
| Query logic + scoping | `apps/search/services.py` (one `_search_*` per type, `_SEARCHERS` registry) |
| Validation + HTTP | `apps/search/views.py` (plain `APIView`, no serializer — dashboard's reasoning) |

**Adding a new searchable type later:** write `_search_<type>` copying an
existing one (scope queryset exactly like that module's LIST endpoint),
register it in `_SEARCHERS`, extend `allowed_types` if role-gated, add the
index(es) to the model's Meta + a migration depending on
`("search", "0001_enable_pg_trgm")` if trigram, and add scoping tests.

## 4. Beginner mistakes this module dodges (recap)

1. Trigram index on the raw column while querying `UPPER(col)` — dead index.
   Caught by `EXPLAIN`, fixed with `OpClass(Upper(...))`.
2. FTS index with one config, query with another (or default) — dead index.
   Config pinned in one constant.
3. Believing FTS covers substring search (it can't: "epor" ≠ a stem) or that
   LIKE covers word search (it can't: "deploying" ≢ "deployed") — hybrid OR.
4. `COUNT(*)` per type for "N results" badges — doubled cost; `has_more` via
   `limit+1` instead.
5. Forgetting `.distinct()` after a scoping JOIN — duplicate hits for staff.
6. Empty list instead of absent key for forbidden types — existence leak.
7. Caching search responses "because dashboard does" — different access
   pattern, zero hit rate.
