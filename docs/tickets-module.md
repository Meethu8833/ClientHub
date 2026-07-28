# Support Ticket Module

Backend for client support: tickets with a controlled lifecycle, priorities
driving SLA deadlines, a reply thread, escalation (manual + automatic), and
admin-managed categories. Lives in `apps/tickets`; tickets are registered in
the attachments registry, so notes, documents and the activity timeline all
work on them.

## Concepts

- **Ticket** — one client-reported case, always tied to a `Client` (PROTECT)
  and optionally to the `Contact` who reported it (SET_NULL). **Never
  deleted** — not even soft-deleted: support history with holes is worthless
  for audits and SLA reporting. Finished tickets are *closed*.
- **Lifecycle (`status`)** — a real state machine, not a free field:

  ```
  open ──▶ in_progress ◀──▶ waiting_on_client
              │                    │
              ▼                    ▼
           resolved ───────────▶ closed
              ▲    (reopen)        │
              └────────────────────┘
  ```

  Legal moves live in `Ticket.ALLOWED_TRANSITIONS`; anything else is a 400.
  `status` is **read-only in every serializer** — it moves only through the
  action endpoints, because transitions carry side effects (timestamps,
  required summary, history rows). Invariant, DB-enforced by CheckConstraint:
  `status ∈ {resolved, closed} ⇔ resolved_at set`.
- **Priority** — `low/medium/high/urgent` (`TicketPriority`, module-level so
  `SlaPolicy` shares the identical choices). Changing priority re-stamps the
  SLA deadlines and writes a timeline event.
- **SLA** — `SlaPolicy`: one row per priority (seeded by data migration
  `0002`, tuned by admins via `PATCH /sla-policies/{id}/`), promising
  `first_response_minutes` and `resolution_minutes`. On ticket creation the
  deadlines are **denormalized** onto the ticket (`first_response_due_at`,
  `resolution_due_at`): the promise made at intake must not silently change
  when the policy is edited later, and overdue filtering needs an indexed
  column. The first **public** reply stamps `first_response_at` (internal
  notes don't stop the clock). "Overdue" is always *computed* against now()
  — model properties for serializers, mirrored SQL in `TicketFilter` for
  `?overdue=true` and in the sweep command.
- **Escalation** — a *flag*, not a status (it changes who is watching, not
  where the work is): `is_escalated` + who/when/why. Manual via
  `POST /tickets/{id}/escalate/` (any role — raising the flag is the point);
  automatic via the `escalate_overdue_tickets` management command (cron,
  `--dry-run` supported), which escalates unfinished, unescalated tickets
  past either deadline with `actor=None` (= "the system", honestly shown on
  the timeline).
- **Categories** — `TicketCategory` is a **table**, not TextChoices, by §4's
  own criterion: admins change categories at runtime; releases don't.
  PROTECTed by tickets and therefore never deleted over the API — retired
  via `is_active=false` (existing tickets keep it; new ones can't pick it).
- **Replies** — `TicketReply`: append-only thread (no edit/delete — first-
  response times and dispute audits are computed from it), oldest-first.
  `is_internal=true` marks team-only notes a future client portal must never
  render. No replies on closed tickets.
- **Resolution** — `resolve` **requires a summary** (what was done — the
  next agent's playbook when the client calls again); `close` confirms;
  `reopen` clears the resolution bookkeeping and bumps `reopened_count`
  (a fix-quality metric).

## Visibility & permissions

Tickets are a **shared queue**: every authenticated role sees every ticket
(unlike leads/deals — support is handed around constantly). What STAFF may
*change* is restricted instead, via `owner_field = "assignee"`:

| Action | ADMIN/MANAGER | STAFF |
|---|---|---|
| view / create / reply / escalate / reopen | ✅ | ✅ |
| `claim` (self-assign) | ✅ | ✅ unassigned or own only |
| `assign` (hand to someone) | ✅ | ❌ |
| PATCH fields, `resolve`, `close` | ✅ | own (assigned) tickets only |
| categories write | ✅ | ❌ (read ok) |
| SLA policies write | admin only | ❌ (read ok) |

## Endpoints

```
/api/v1/tickets/                GET (filter/search/order), POST — no DELETE
/api/v1/tickets/{id}/           GET, PATCH (fields only, never status/client)
/api/v1/tickets/{id}/replies/   GET thread, POST {body, is_internal}
/api/v1/tickets/{id}/claim/     POST
/api/v1/tickets/{id}/assign/    POST {assignee_id|null}  (null → back to queue)
/api/v1/tickets/{id}/escalate/  POST {reason?}
/api/v1/tickets/{id}/resolve/   POST {summary}
/api/v1/tickets/{id}/close/     POST
/api/v1/tickets/{id}/reopen/    POST
/api/v1/ticket-categories/      CRUD minus DELETE (retire via is_active)
/api/v1/sla-policies/           GET all; PATCH admin
```

Filters: `status, priority, client, category, assignee, is_escalated,
unassigned, overdue, created_after/before`; search on subject/description/
client name. Assigning an OPEN ticket auto-starts it; unassigning an
IN_PROGRESS ticket sends it back to OPEN — status always tells the truth
about the assignee.

## Cron

```
*/15 * * * *  cd backend && python manage.py escalate_overdue_tickets
```

## Files

`models.py` (4 models + state machine + overdue properties) · `services.py`
(every transition, SLA stamping, replies — all `transaction.atomic`, all
writing Activity rows) · `serializers.py` · `filters.py` · `views.py` ·
`migrations/0002_seed_sla_policies.py` ·
`management/commands/escalate_overdue_tickets.py` · `tests/` (27 tests).
Cross-app touches: `core/attachments.py` (+`ticket` slug),
`activities.Activity.Verb.ESCALATED`, settings + root urls.
