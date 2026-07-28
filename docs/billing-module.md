# Billing Module (Invoices & Payments)

Phase 2 of ARCHITECTURE.md: the `billing` app — `Invoice`, `InvoiceItem`,
`Payment`. A quotation is an *offer* ("we could do this for ₹X"); an invoice is
a *demand* ("you owe us ₹X by this date"). That one-sentence difference drives
every design decision below.

---

## 1. Concepts

### 1.1 The invoice lifecycle

```
            issue                    payments arrive
  DRAFT ───────────► ISSUED ───────► PARTIALLY_PAID ───────► PAID
    │                  │                   ▲    │              │
  delete             void                  └────┴──────────────┘
 (allowed)      (no payments only)        payment DELETED rolls back
```

- **DRAFT** — a worksheet. Fully editable (header and lines), deletable, has
  **no invoice number**. Nothing about it exists legally yet.
- **ISSUED** — the moment of truth. `issue` assigns the legal number, stamps
  `issue_date`, fixes `due_date`, and **freezes the document**: no edits, no
  item changes, no deletion, ever. An issued invoice is a ledger entry.
- **PARTIALLY_PAID / PAID** — *derived* states. They are never set by hand;
  they follow from comparing `amount_paid` (the sum of Payment rows) with
  `grand_total`. Deleting a mis-entered payment rolls the status back — the
  status is arithmetic, so it moves in both directions.
- **VOID** — the "it should never have gone out" exit for an issued invoice
  (wrong client, wrong amount). Requires a reason; blocked once any payment
  exists (received money makes it a refund/credit-note problem, not an "it
  never counted" problem). The number stays burned — see §1.6.
- **OVERDUE is not a status.** It is a *condition*: money still owed and
  `due_date < today`. Exposed as the `is_overdue` / `days_overdue` properties
  and the `?overdue=true` filter. A status would need a cron to set it and
  logic to un-set it on payment; a property is derived truth with no moving
  parts (same call as ticket escalation being a flag, and quotation expiry
  being `is_expired` + filter).

### 1.2 Due dates and payment terms

"Net 30" means: payment is due 30 days after the invoice is issued.
`payment_terms_days` (default 30) holds the terms; at **issue** time the
service stamps `due_date = issue_date + terms` unless an explicit `due_date`
was set (a contract may fix an exact calendar date). The clock starts at
*issue*, not at draft creation — the client's obligation begins when a demand
reaches them, not when we started typing.

### 1.3 Payments

A `Payment` row is a record of real money received: amount, the date it landed
on the bank statement (`received_on` — distinct from `created_at`, when a
human typed it in), method, and a reference (UTR / cheque number) so it can be
matched to the statement. Rules:

- Only an **owing** invoice (issued / partially paid) accepts payments.
- **No overpayment**: a payment may not exceed `balance_due`. Accepting extra
  money silently would strand a client credit balance we have no machinery for.
- Payments are **append-then-correct**: never edited (a receipt is a fact);
  a mis-entry is *deleted* by a manager and re-entered, and both moves land on
  the activity trail — the correction is visible, not silent.
- Recording locks the invoice row (`select_for_update`) so two clerks entering
  the same cheque serialize instead of double-crediting.

### 1.4 Outstanding balance

`balance_due = grand_total − amount_paid` — the number every billing screen
lives on. `amount_paid` is denormalized onto the invoice (kept in sync by the
two payment services) so list screens can show and *filter* balances without
joining payments. `PAID` is simply the state where the balance hits zero, and
`paid_at` records when.

### 1.5 Tax (and discounts)

Same money pipeline as quotations, because the same laws apply:

```
line_subtotal (qty × price)
  − line discount %
  − invoice-level discount %
  = taxable_amount            ← tax is charged on what is actually payable
  × tax_percent               ← rate lives on the LINE (one invoice can mix
  = line_tax                    18% services with 0%-rated lines)
```

All money is `Decimal`; every stage rounds to 2 places with `ROUND_HALF_UP`
(commercial rounding); totals are sums of *rounded* lines so the printed lines
add up to the printed total. Invoice-level discount is percent-only — a fixed
"₹5,000 off" cannot be lawfully allocated across lines with different tax
rates. Totals are denormalized and recomputed by `services.recompute_totals()`
on every money-moving write; once issued they are frozen history.

### 1.6 Invoice number generation — why it differs from quotations

Tax law (GST rule 46 in India, and equivalents elsewhere) requires invoice
numbers to form a **consecutive, gapless series**. Quotation numbers may have
gaps (a deleted draft's number is simply lost — fine for offers). For invoices
we get gaplessness *structurally*:

1. Drafts hold **no number** (`invoice_number` is NULL — a conditional unique
   constraint ignores NULLs, where an empty string would collide).
2. The number `INV-<year>-NNNN` is assigned **at issue**, inside a transaction,
   with `select_for_update()` serializing concurrent issues (the unique
   constraint is the backstop for the empty-year race).
3. Issued invoices can **never be deleted** — a mistake is VOIDED, so its
   number stays visible in the books as a void row, not a hole in the series.

Deleting a draft therefore never consumes a number, and the issued series is
gapless by construction — no "number reservation" table needed.

---

## 2. Data model

| Model | Key fields | Notes |
|---|---|---|
| `Invoice` | `invoice_number` (NULL until issue, conditionally unique), `client` PROTECT, `contact` SET_NULL, `project` PROTECT nullable, `quotation` SET_NULL nullable (not unique — staged billing), money totals + `amount_paid` (denormalized), `payment_terms_days`, `issue_date`/`due_date`, `terms`/`notes`, status + `issued_at`/`paid_at`/`voided_at`/`void_reason`, `created_by` SET_NULL | CheckConstraints: issued ⇒ number+dates present; paid ⇒ `paid_at`; void ⇒ `voided_at`; discount 0–100; `amount_paid ≥ 0` |
| `InvoiceItem` | description, qty, unit, unit_price, discount %, tax % (default 18), position | CASCADE (only numberless drafts are deletable); money pipeline as properties |
| `Payment` | `invoice` **PROTECT**, amount (> 0), `received_on`, method choices, reference, notes, `recorded_by` SET_NULL | ordering `-received_on`; no PATCH anywhere |

Deliberate duplication: `InvoiceItem` mirrors `QuotationItem` rather than
sharing a base class — the two documents freeze at different moments and must
be free to evolve apart (invoice math is bound to tax law).

## 3. Permissions

The §8 matrix Billing row: **ADMIN/MANAGER full, STAFF nothing — not even
read.** One `IsManagerOrAdmin` on every viewset; no queryset scoping needed.
The `invoice` attachment slug is likewise invisible to staff in
`core/attachments.get_visible_target`.

## 4. API

```
GET/POST      /api/v1/invoices/                 list (filters below) / create draft
POST          /api/v1/invoices/from-quotation/  {quotation_id} → 201 draft copied
                                                from an ACCEPTED quotation
GET/PATCH/DEL /api/v1/invoices/{id}/            detail / draft-only edits / draft-only delete
GET/POST      /api/v1/invoices/{id}/items/      lines / add line (draft only)
PATCH/DELETE  /api/v1/invoice-items/{id}/       one line, flat (draft only)
POST          /api/v1/invoices/{id}/issue/      draft → issued; number assigned HERE
POST          /api/v1/invoices/{id}/void/       {reason} issued → void (no payments)
GET/POST      /api/v1/invoices/{id}/payments/   receipts / record money
DELETE        /api/v1/payments/{id}/            remove a mis-entered receipt
```

Filters: `status`, `client`, `project`, `invoice_number`, `unpaid`, `overdue`,
`due_before`, `min_total`/`max_total`, `issued_after`/`issued_before`;
`?search=` on number and client name; ordering on dates and money fields.

Validation highlights: client immutable after create; contact/project must
belong to the client; `due_date` never in the past at write or issue;
`received_on` never in the future; every 400 explains itself.

## 5. Activity trail

`STATUS_CHANGED` for issue/void/paid-state moves, plus two new verbs:
`PAYMENT_RECORDED` (amount, method, remaining balance) and `PAYMENT_DELETED`
(amount, restored balance) — money moves carry their numbers on the timeline.

## 6. Out of scope (deliberately)

- **Credit notes / refunds** — the correct instrument once a paid or partly
  paid invoice is wrong. Until then: void + reissue covers the pre-payment
  case.
- **Client credit balances** (hence the overpayment wall).
- **PDF export** (roadmap §, with the frontend).
- **Time-entry → invoice generation** — the natural next slice: pull a
  project's unbilled `TimeEntry` rows into draft lines.

## 7. Gotcha found while building

`recompute_totals` originally read `invoice.items.all()`. The viewset fetches
invoices with `prefetch_related("items")`, so inside the nested
`POST /items/` action that returned the **stale prefetch cache** — totals
missing the line just added. The same latent bug existed in quotations (its
tests only edited lines via the flat route, which has no prefetch). Both now
query the table directly; a regression test guards the quotations path.
