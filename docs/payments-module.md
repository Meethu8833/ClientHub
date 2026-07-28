# Payment Management (billing app, part 2)

This module extends the billing backend (`docs/billing-module.md`) with the
full life of a payment: the **pending → completed/bounced lifecycle**,
**refunds**, and **bank reconciliation**, plus a global **payments register**
and a **cash summary** endpoint. Nothing here is a new app — money against an
invoice is still the billing app's business; we grew the `Payment` model and
added a `Refund` model beside it.

---

## 1. The concepts (read this before the code)

### 1.1 The payment lifecycle

The first module treated a payment as a single event: money arrived, record
it. Real money is messier — for many instruments there is a **gap between
"the client paid" and "we have the money"**:

| Moment | Cheque | UPI / cash | Bank transfer |
|---|---|---|---|
| Client hands over payment | day 0 | day 0 | day 0 |
| Money actually usable by us | day 2–5 (or **never**, if it bounces) | day 0 | usually day 0–1 |

So a `Payment` now has a tiny state machine of its own:

```
                 ┌──clear───▶ completed   (money is real; counts toward the invoice)
recorded ──▶ pending
                 └──bounce──▶ bounced     (instrument failed; kept on record, never counts)

recorded ──▶ completed                    (instant methods skip pending entirely)
```

Rules that fall out of taking the gap seriously:

- **Only `completed` money moves the invoice.** A pending cheque changes
  nothing on `amount_paid` or the invoice status — a promise is not money.
- **`bounced` is terminal and is never deleted.** The bounce is a fact about
  the client (their cheques fail). Deleting it would erase risk history the
  next person quoting them deserves to see.
- **You cannot *record* a payment as bounced** — bounced is an outcome you
  reach through the `bounce` action, never a starting state.
- **A completed payment has no transitions.** If it was entered wrongly, the
  correction is *delete + re-enter* (both moves visible on the trail), not a
  silent status edit.

### 1.2 Partial payments (recap — built in part 1, unchanged)

An invoice accepts any number of payments; the invoice's paid status is
**derived, never typed**: `issued → partially_paid → paid` purely from
comparing money received against `grand_total`. The overpayment wall rejects
any receipt larger than the remaining balance (we have no "client credit
balance" feature, so extra money would be stranded).

New in this part: the wall is applied **twice** for pending payments — once
at record time (you can't even *promise* more than is owed) and again at
`clear` time, because the balance may have moved while the cheque sat at the
bank. Two cheques can each fit the balance when recorded, yet the second one
to clear may no longer fit — exactly like real banking, the late one is
refused and must be handled by hand.

### 1.3 Refunds

A refund is **money deliberately sent back** — a real second bank movement
with its own date, reference and reason. It is *not* the same as deleting a
payment:

| | Delete a payment | Refund |
|---|---|---|
| Meaning | "that receipt never happened" (typo, wrong invoice) | "it happened — and then we returned the money" |
| Bank statement | shows nothing (there was nothing) | shows TWO lines: money in, money out |
| What survives | only the activity-trail entries | both rows, forever |

Design decisions worth understanding:

- **A refund hangs off the *payment*, not the invoice.** Money goes back the
  way it came (gateway rules literally require this for cards), and the cap
  "you can't return more than this receipt brought in, minus what already
  went back" falls out naturally. It also means a refunded payment can never
  be deleted — the `PROTECT` FK plus a service guard enforce it.
- **Gross and refunded are stored separately** on the invoice:
  `amount_paid` (sum of completed payments) and `amount_refunded` (sum of
  refunds). Finance screens must show *"received ₹23,600, refunded ₹5,000"*
  as two numbers; netting them into one column would destroy the gross
  figure the books need. The derived views are properties:
  `net_paid = amount_paid − amount_refunded` and
  `balance_due = grand_total − net_paid`.
- **A refund reopens the balance.** The status mapper runs on `net_paid`, so
  refunding a paid invoice walks it back to `partially_paid` or even
  `issued` — the client owes that money again. (The common alternative — a
  terminal `refunded` status plus credit notes — is the full accounting
  answer; we deliberately chose the simpler model and documented the trade.)
- **`reason` is mandatory**, same rule as voiding: money leaving the company
  without a written why is an audit red flag.
- Refunds follow the same **append-then-correct** discipline: no edits ever;
  a mis-entered refund is deleted (manager) and re-entered, and deletion
  simply restores a previously-valid state, so it needs no overpay check.

### 1.4 Payment status vs invoice status

Two different state machines that must not be confused:

- **Invoice status** (`draft/issued/partially_paid/paid/void`) answers *"how
  much of this bill is settled?"* — derived from money arithmetic.
- **Payment status** (`pending/completed/bounced`) answers *"is this one
  receipt real money yet?"* — moved only by the `clear`/`bounce` actions.

The link between them is exactly one line: only `completed` payments are
allowed to enter the invoice's arithmetic.

### 1.5 Reconciliation

Reconciliation is the accounting ritual of proving your records against the
bank's: every payment row you claim should match a real statement line, and
every statement line should have a row. Our design:

- The stamp is the flag: `reconciled_at`/`reconciled_by` on the payment
  (`NULL` = unmatched). No separate boolean to fall out of sync —
  `is_reconciled` is a property over the timestamp.
- **Only completed payments can reconcile** (a DB CheckConstraint backs the
  service guard): the bank can only ever show money that actually moved.
- **Reconciled = locked.** A reconciled payment cannot be deleted — it has
  been confirmed to exist in the outside world; deleting it would make the
  books disagree with the bank. Wrong match? `unreconcile` first (both moves
  stay on the trail), then correct.
- The workflow is statement-side: open the bank statement, pull
  `GET /payments/?status=completed&reconciled=false&received_after=…`, and
  tick rows off one by one via `POST /payments/{id}/reconcile/`. The
  `summary` endpoint shows how much is still unmatched.

We reconcile payments only (not refunds) — a real ledger reconciles every
movement in both directions; that's noted as a conscious scope cut.

---

## 2. What was added where

| Piece | File | What |
|---|---|---|
| `Payment.status` + `ALLOWED_TRANSITIONS`, `reconciled_at/by`, `amount_refunded`/`refundable_amount` props | `billing/models.py` | the lifecycle + lock fields |
| `Refund` model | `billing/models.py` | payment FK `PROTECT`, amount, `refunded_on`, method, reference, **reason**, recorder |
| `Invoice.amount_refunded`, `net_paid`, reworked `balance_due` | `billing/models.py` | gross/refund split |
| `clear_payment`, `bounce_payment`, `record_refund`, `delete_refund`, `reconcile_payment`, `unreconcile_payment`; `_sync_paid_status` now maps **net_paid**; `record_payment`/`delete_payment` are pending-aware; void ignores bounced rows | `billing/services.py` | every function locks the invoice row and writes the trail |
| `PaymentFilter` | `billing/filters.py` | status/method/reconciled/client/dates/amount/reference |
| Register + actions + summary, `RefundViewSet` | `billing/views.py` | see API table |
| Verbs `payment_cleared`, `payment_bounced`, `refund_recorded`, `refund_deleted`, `reconciled` | `activities/models.py` | reconciled carries `{"reconciled": bool}` both directions |
| Read-only `Payment`/`Refund` admin | `billing/admin.py` | admin is a window, not a door — services are the only writers |

DB constraints added: `refund_amount_positive`,
`invoice_amount_refunded_not_negative`,
`payment_reconciled_only_when_completed`, plus an index on
`(status, received_on)` for the reconciliation screen.

## 3. API

All routes ADMIN/MANAGER only (STAFF has zero billing access — §8).

| Route | Verb | What |
|---|---|---|
| `/invoices/{id}/payments/` | POST | record money; body now takes optional `status`: `pending` \| `completed` (default) |
| `/payments/` | GET | global payments register; `?invoice= &client= &method= &status= &reconciled= &reference= &received_after= &received_before= &min_amount= &max_amount=` |
| `/payments/{id}/` | GET / DELETE | one receipt / remove a mis-entry (refused if reconciled or refunded) |
| `/payments/{id}/clear/` | POST | pending → completed; money counts now; re-checks the balance |
| `/payments/{id}/bounce/` | POST | pending → bounced; terminal, kept on record |
| `/payments/{id}/reconcile/` | POST | stamp as matched to the bank statement; locks the row |
| `/payments/{id}/unreconcile/` | POST | undo a wrong match |
| `/payments/{id}/refunds/` | GET / POST | list / send money back — `{amount, refunded_on, reason(required), method?, reference?}` |
| `/refunds/{id}/` | DELETE | remove a mis-entered refund |
| `/payments/summary/` | GET | cash dashboard for `?received_after=&received_before=`: `received` (+ `by_method`), `pending`, `bounced`, `unreconciled`, `refunded` — each `{total, count}`, aggregated in SQL |

Payment rows everywhere now include `status`, `is_reconciled`,
`reconciled_at/by`, `amount_refunded`, `refundable_amount` and nested
`refunds`; register rows add the invoice number + client. Invoice list/detail
adds `amount_refunded` and `net_paid`.

Status codes follow the house idiom: 400 for every rule violation
(transition, cap, lock), 403 for role, 404 for missing, 201 on create,
204 on delete.

## 4. Beginner traps this module avoids (and you should remember)

1. **Trusting a typed status.** Nothing lets a human write `paid`,
   `completed`-with-money, or `reconciled` directly — every state is either
   derived from arithmetic or moved by a guarded action. If a status can be
   typed, it will eventually lie.
2. **Counting promised money.** Pending ≠ received. Any report or status
   that includes uncleared cheques overstates your cash.
3. **Refund = delete.** Deleting destroys history; refunding records
   history. Pick by asking "did the money actually move twice?"
4. **One net column.** Store gross-in and gross-out separately; derive net.
   You can always net two numbers; you can never un-net one.
5. **Race-free money.** Every writer `select_for_update()`s the invoice row;
   the clear-time re-check exists precisely because the world changes while
   an instrument is in flight.
6. **Floating point.** Still `Decimal` everywhere, `ROUND_HALF_UP`, 2dp.

## 5. Tests

`apps/billing/tests/test_payment_management.py` — 16 tests: pending doesn't
count until cleared; bounce is terminal and never counts; completed can't
transition; can't record as bounced; clear re-checks the balance; void OK
with only bounced rows; deleting pending moves no money; refund reopens a
paid invoice; per-payment refund cap; refund needs completed + reason;
refunded payment undeletable until refunds removed; reconcile locks/unlocks;
only completed reconciles; register filters; summary numbers + bad-date 400;
staff 403 everywhere; every move on the activity trail.

Full suite after this module: **290 passed**.
