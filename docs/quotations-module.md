# Quotation Management Module

A quotation is a **priced offer** sent to a client before work starts: line
items, discounts, taxes, a validity window, an internal approval gate, a
client decision, and versioned revisions. App: `apps/quotations/`
(user-requested addition beyond ARCHITECTURE.md, same precedent as tickets;
the future `sales` app's Deal will link to quotations, not replace them).

## Concepts

### The lifecycle (state machine)

```
draft ──submit──▶ pending_approval ──approve──▶ approved ──send──▶ sent
  ▲                     │                          │                │
  └──request-changes────┘                          │                ├─▶ accepted   (terminal)
                                                   │                ├─▶ declined   (terminal)
draft / pending_approval / approved ──cancel──▶ cancelled           ├─▶ expired    (terminal, sweep)
                                                   │                │
                                                   └────revise──────┴─▶ superseded (terminal)
```

- `status` is **read-only over PATCH**; every move is a POST action →
  `services.py`, because every move has side effects (stamps, guards,
  history rows). Illegal moves 400 via `ALLOWED_TRANSITIONS`.
- **Editing is draft-only.** Fields and line items freeze at submit; the only
  way a delivered offer changes is `revise` (below). Only never-submitted
  drafts may be DELETEd — anything else is business history (cancel instead).

### Money: discounts → then tax

All money is `Decimal`, rounded per line to 2dp with `ROUND_HALF_UP`
(commercial rounding). Per line:

```
line_subtotal  = quantity × unit_price
− line discount (item.discount_percent)
− quote-level discount (quotation.discount_percent, uniform %)
= taxable_amount
+ tax (taxable_amount × item.tax_percent)      ← tax AFTER discounts (GST rule)
= line_total
```

- `tax_percent` lives **on the line** (GST rates differ per service type;
  default 18% = IT services). `discount_percent` exists at both levels; the
  quote-level one is **percent only** — a fixed "₹5,000 off" would have to be
  allocated across lines with different tax rates (lawful-tax-math rabbit
  hole, deliberately out of scope).
- Quote totals (`subtotal`, `discount_total`, `tax_total`, `grand_total`) are
  **denormalized** onto the quotation and recomputed by
  `services.recompute_totals()` on every item/discount write — stored so list
  screens can sort/filter on them and sent quotes stay frozen history.

### Numbering & versioning

- `quote_number` = `QT-<year>-<seq>` (restarts yearly), assigned once at
  creation inside the create transaction (`select_for_update` + unique
  constraint backstop). Gaps are fine — only tax invoices need gapless.
- `revise` cuts version N+1: same `quote_number`, `version+1`, cloned header
  + lines, fresh empty `valid_until`, linked via `revision_of`. Unique pair
  `(quote_number, version)`. Old version: APPROVED/SENT → `superseded` (only
  one live version ever); DECLINED/EXPIRED keep their status (history is
  history). ACCEPTED is never revisable (new business = new quote), and each
  version revises at most once (a chain, not a tree).

### Approval

- `submit` gates completeness: ≥1 item + a future `valid_until`.
- `approve` / `request-changes` are **manager/admin only**, and the approver
  may not be the author (segregation of duties). Request-changes requires a
  note and returns the quote to draft; the note lands in `approval_note`.

### Validity / expiry

- `valid_until` optional while drafting, required at submit, re-checked at
  send. `is_expired` is computed live (SENT + past date).
- Nightly cron `python manage.py expire_quotations` moves lapsed SENT quotes
  to `expired` (actor=None history row). The gap between midnight and the
  sweep is safe: `accept` checks `is_expired` itself.

## Visibility & permissions

Follows the **Leads/Deals row** of the §8 matrix (sales records with money):

| | ADMIN / MANAGER | STAFF |
|---|---|---|
| See / create | all | own (`created_by`) only — out-of-scope 404s |
| Edit draft, items, submit/send/accept/decline/cancel/revise | any | own only |
| Approve / request changes | ✅ (not own quotes) | ❌ 403 |

Notes/documents attach via slug `quotation` (registry in
`core/attachments.py`, staff scoped to own quotes there too).

## Endpoints

```
/api/v1/quotations/                       GET list (filters: status, client,
                                          created_by, expired, expiring_before,
                                          min/max_total, created_after/before;
                                          ?search= number/title/client;
                                          ?ordering= created_at/grand_total/valid_until)
                                          POST create draft
/api/v1/quotations/{id}/                  GET detail · PATCH (draft only)
                                          DELETE (draft only)
/api/v1/quotations/{id}/items/            GET lines · POST add line (draft only)
/api/v1/quotation-items/{id}/             PATCH / DELETE one line (draft only)
/api/v1/quotations/{id}/submit/           POST
/api/v1/quotations/{id}/approve/          POST {note?}     manager, not author
/api/v1/quotations/{id}/request-changes/  POST {note}      manager
/api/v1/quotations/{id}/send/             POST
/api/v1/quotations/{id}/accept/           POST             expiry-guarded
/api/v1/quotations/{id}/decline/          POST {reason?}
/api/v1/quotations/{id}/cancel/           POST
/api/v1/quotations/{id}/revise/           POST → 201 new draft version
```

Every mutation responds with the full detail shape. Item reads include the
whole computed money pipeline (`line_subtotal`…`line_total`) so the frontend
never re-implements rounding.

## Cron

```
# nightly, after midnight local time
python manage.py expire_quotations
```

## Files

```
apps/quotations/
├── models.py        Quotation (state machine, totals, trails), QuotationItem (line math)
├── services.py      numbering, recompute_totals, every transition, revise
├── serializers.py   List / Detail / Write + item + action bodies
├── views.py         QuotationViewSet (+9 actions), QuotationItemViewSet (flat writes)
├── filters.py       pipeline filters incl. expired / expiring_before
├── urls.py          /quotations/, /quotation-items/
├── management/commands/expire_quotations.py
└── tests/           30 tests: money math, workflow, roles, versioning, expiry
```
