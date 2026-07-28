"""
Side-effectful billing logic (§11: views stay thin). Numbering, totals,
issue/void, and the payment bookkeeping all live here — each function is one
atomic unit of "change + its bookkeeping + its history row".

The invariant this file exists to protect: an invoice's paid status is
ALWAYS derived from its money rows. amount_paid is the sum of COMPLETED
Payment rows, amount_refunded is the sum of Refund rows, and
_sync_paid_status is the only mapper from their difference (net_paid) to
issued/partially_paid/paid. The functions in this file are the only writers
of any of the three. No API path can set them directly, so "the invoice says
paid" always means "the money is on record".
"""

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.activities.models import Activity
from apps.activities.services import record
from apps.quotations.models import Quotation

from .models import Invoice, InvoiceItem, Payment, Refund

ZERO = Decimal("0.00")


# -- numbering ----------------------------------------------------------------


def _next_invoice_number() -> str:
    """
    "INV-<year>-<seq>", restarting each year, zero-padded so text ordering ==
    numeric ordering. Same mechanics as quotation numbering with one crucial
    difference in WHEN it runs: only at issue. Draft deletion therefore never
    consumes a number, and issued invoices are undeletable — so the issued
    series is GAPLESS, which is what tax law (GST rule 46) demands.

    Concurrency: select_for_update() locks the current latest row so two
    simultaneous issues serialize; the conditional UniqueConstraint is the
    backstop for the empty-year race.
    """
    prefix = f"INV-{timezone.localdate().year}-"
    latest = (
        Invoice.objects.select_for_update()
        .filter(invoice_number__startswith=prefix)
        .order_by("-invoice_number")
        .values_list("invoice_number", flat=True)
        .first()
    )
    seq = int(latest.removeprefix(prefix)) + 1 if latest else 1
    return f"{prefix}{seq:04d}"


# -- totals -------------------------------------------------------------------


def recompute_totals(invoice: Invoice) -> Invoice:
    """
    Re-derive the stored totals from the lines, after every write that can
    move money (item add/edit/delete, invoice discount change). Sums are over
    per-line ROUNDED figures so the printed lines add up to the printed total.
    """
    # Query the table, NOT invoice.items.all(): the viewset fetches invoices
    # with prefetch_related("items"), and .all() would happily return that
    # stale cache — computing totals that miss the line just added.
    items = list(InvoiceItem.objects.filter(invoice=invoice))
    subtotal = sum((i.line_subtotal for i in items), ZERO)
    taxable = sum((i.taxable_amount for i in items), ZERO)
    invoice.subtotal = subtotal
    invoice.discount_total = subtotal - taxable  # line + invoice-level discounts combined
    invoice.tax_total = sum((i.line_tax for i in items), ZERO)
    invoice.grand_total = taxable + invoice.tax_total
    invoice.save(
        update_fields=["subtotal", "discount_total", "tax_total", "grand_total", "updated_at"]
    )
    return invoice


# -- guards -------------------------------------------------------------------


def _check_transition(invoice: Invoice, new_status: str) -> None:
    if new_status not in Invoice.ALLOWED_TRANSITIONS[invoice.status]:
        raise ValidationError(
            {
                "status": f"Cannot move a {invoice.get_status_display().lower()} "
                f"invoice to {new_status}."
            }
        )


def _require_draft(invoice: Invoice) -> None:
    """Field/item edits are draft-only — an issued invoice is a legal
    document; corrections happen through void + reissue (or a credit note,
    which is out of scope for now)."""
    if not invoice.is_editable:
        raise ValidationError(
            {"detail": "Only a draft can be edited — void the invoice and issue a new one."}
        )


def _change_status(invoice: Invoice, new_status: str, actor) -> Invoice:
    """The one gate every move goes through: validate, save, one history row."""
    _check_transition(invoice, new_status)
    old_status = invoice.status
    invoice.status = new_status
    invoice.save()
    record(
        actor=actor,
        target=invoice,
        verb=Activity.Verb.STATUS_CHANGED,
        changes={"field": "status", "from": old_status, "to": new_status},
    )
    return invoice


# -- create / update ----------------------------------------------------------


@transaction.atomic
def create_invoice(*, invoice: Invoice, actor) -> Invoice:
    """Persist a new draft. NO number yet — that happens at issue."""
    invoice.created_by = actor
    invoice.save()
    record(actor=actor, target=invoice, verb=Activity.Verb.CREATED, changes={})
    return invoice


@transaction.atomic
def update_invoice(*, invoice: Invoice, actor) -> Invoice:
    """Persist draft field edits; recompute because discount_percent may be
    among them."""
    _require_draft(invoice)
    invoice.save()
    recompute_totals(invoice)
    record(actor=actor, target=invoice, verb=Activity.Verb.UPDATED, changes={})
    return invoice


@transaction.atomic
def create_from_quotation(*, quotation: Quotation, actor) -> Invoice:
    """
    Draft an invoice from an ACCEPTED quotation: header + lines copied, the
    source linked. Only accepted offers become bills — invoicing a declined
    or still-pending quote would demand money nobody agreed to pay.

    Deliberately NOT one-per-quotation: staged billing (advance + delivery)
    means several invoices may draw on one quote. The link is for traceability,
    not exclusivity.
    """
    if quotation.status != Quotation.Status.ACCEPTED:
        raise ValidationError(
            {"detail": "Only an accepted quotation can be turned into an invoice."}
        )
    invoice = Invoice(
        client=quotation.client,
        contact=quotation.contact,
        quotation=quotation,
        currency=quotation.currency,
        discount_percent=quotation.discount_percent,
        terms=quotation.terms,
    )
    invoice = create_invoice(invoice=invoice, actor=actor)
    for item in quotation.items.all():
        InvoiceItem.objects.create(
            invoice=invoice,
            description=item.description,
            quantity=item.quantity,
            unit=item.unit,
            unit_price=item.unit_price,
            discount_percent=item.discount_percent,
            tax_percent=item.tax_percent,
            position=item.position,
        )
    return recompute_totals(invoice)


# -- items --------------------------------------------------------------------


@transaction.atomic
def add_item(*, invoice: Invoice, item: InvoiceItem, actor) -> InvoiceItem:
    _require_draft(invoice)
    item.invoice = invoice
    if not item.position:  # default: append to the end of the printed table
        last = invoice.items.order_by("-position").first()
        item.position = (last.position + 1) if last else 1
    item.save()
    recompute_totals(invoice)
    record(
        actor=actor,
        target=invoice,
        verb=Activity.Verb.UPDATED,
        changes={"item_added": item.description},
    )
    return item


@transaction.atomic
def update_item(*, item: InvoiceItem, actor) -> InvoiceItem:
    _require_draft(item.invoice)
    item.save()
    recompute_totals(item.invoice)
    record(
        actor=actor,
        target=item.invoice,
        verb=Activity.Verb.UPDATED,
        changes={"item_updated": item.description},
    )
    return item


@transaction.atomic
def delete_item(*, item: InvoiceItem, actor) -> None:
    _require_draft(item.invoice)
    invoice, description = item.invoice, item.description
    item.delete()
    recompute_totals(invoice)
    record(
        actor=actor,
        target=invoice,
        verb=Activity.Verb.UPDATED,
        changes={"item_removed": description},
    )


# -- lifecycle ----------------------------------------------------------------


@transaction.atomic
def issue_invoice(*, invoice: Invoice, actor) -> Invoice:
    """
    Draft → issued: the moment the document becomes real. Assigns the legal
    number, stamps issue_date, and fixes due_date (explicit date wins; else
    issue_date + payment terms). After this, nothing on it may change.
    """
    _check_transition(invoice, Invoice.Status.ISSUED)
    if not invoice.items.exists():
        raise ValidationError({"detail": "Add at least one line item before issuing."})
    if invoice.due_date is not None and invoice.due_date < timezone.localdate():
        raise ValidationError({"due_date": "The due date is already in the past."})
    invoice.invoice_number = _next_invoice_number()
    invoice.issue_date = timezone.localdate()
    if invoice.due_date is None:
        invoice.due_date = invoice.issue_date + timedelta(days=invoice.payment_terms_days)
    invoice.issued_at = timezone.now()
    return _change_status(invoice, Invoice.Status.ISSUED, actor)


@transaction.atomic
def void_invoice(*, invoice: Invoice, actor, reason: str) -> Invoice:
    """
    Retire an issued invoice that should never have gone out (wrong client,
    wrong amount). Its number stays burned — the gapless series shows the
    void row instead of a hole. Refusing when money has been received is the
    accounting boundary: received money makes it a refund/credit-note case,
    not an "it never counted" case.
    """
    # Bounced payments don't block: no money ever arrived through them, so
    # the "it never counted" reasoning still holds.
    if invoice.payments.exclude(status=Payment.Status.BOUNCED).exists():
        raise ValidationError(
            {"detail": "This invoice has recorded payments — it can no longer be voided."}
        )
    invoice.voided_at = timezone.now()
    invoice.void_reason = reason
    return _change_status(invoice, Invoice.Status.VOID, actor)


# -- payments -----------------------------------------------------------------


def _sync_paid_status(invoice: Invoice, actor) -> Invoice:
    """Map net_paid (cleared money minus refunds) → status. Called only from
    the money writers in this file. Works in BOTH directions: a refund can
    walk a PAID invoice back to PARTIALLY_PAID or even ISSUED."""
    if invoice.net_paid >= invoice.grand_total:
        target = Invoice.Status.PAID
    elif invoice.net_paid > ZERO:
        target = Invoice.Status.PARTIALLY_PAID
    else:
        target = Invoice.Status.ISSUED
    # paid_at mirrors the status: stamped on entering PAID, cleared on leaving.
    if target == Invoice.Status.PAID and invoice.paid_at is None:
        invoice.paid_at = timezone.now()
    if target != Invoice.Status.PAID:
        invoice.paid_at = None
    if target == invoice.status:
        invoice.save()
        return invoice
    return _change_status(invoice, target, actor)


@transaction.atomic
def record_payment(*, invoice: Invoice, payment: Payment, actor) -> Payment:
    """
    Book money (or a promised instrument) against an invoice. Locks the
    invoice row (two clerks entering the same cheque must serialize) and
    forbids overpayment — a client credit balance is an accounting feature we
    don't have, so silently accepting extra money would strand it.

    Only a COMPLETED payment moves amount_paid/status; a PENDING one is just
    a record of an instrument in hand — the money arrives at clear_payment.
    The overpayment wall applies to pending too, so nobody can even PROMISE
    more than is owed (and clear_payment re-checks, because the balance may
    have moved while the cheque sat at the bank).
    """
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status not in Invoice.OWING_STATUSES:
        raise ValidationError(
            {"detail": f"Payments can only be recorded on an issued invoice with a balance "
                       f"(this one is {invoice.get_status_display().lower()})."}
        )
    if payment.amount > invoice.balance_due:
        raise ValidationError(
            {"amount": f"Payment exceeds the outstanding balance ({invoice.balance_due})."}
        )
    payment.invoice = invoice
    payment.recorded_by = actor
    payment.save()
    if payment.status == Payment.Status.COMPLETED:
        invoice.amount_paid += payment.amount
        _sync_paid_status(invoice, actor)
    record(
        actor=actor,
        target=invoice,
        verb=Activity.Verb.PAYMENT_RECORDED,
        changes={
            "payment_id": payment.pk,
            "amount": str(payment.amount),
            "method": payment.method,
            "status": payment.status,
            "balance_due": str(invoice.balance_due),
        },
    )
    return payment


@transaction.atomic
def clear_payment(*, payment: Payment, actor) -> Payment:
    """
    PENDING → COMPLETED: the bank confirmed the instrument; the money is now
    real, so NOW it counts. Re-runs the overpayment wall against today's
    balance: while the cheque was clearing, another payment may have filled
    the invoice — in that case the clerk must delete/adjust first, exactly
    what a bank does when a second cheque lands on a settled account.
    """
    invoice = Invoice.objects.select_for_update().get(pk=payment.invoice_id)
    _check_payment_transition(payment, Payment.Status.COMPLETED)
    if payment.amount > invoice.balance_due:
        raise ValidationError(
            {"detail": f"Clearing this payment would exceed the outstanding balance "
                       f"({invoice.balance_due}) — the invoice received other money "
                       f"while it was pending."}
        )
    payment.status = Payment.Status.COMPLETED
    payment.save(update_fields=["status", "updated_at"])
    invoice.amount_paid += payment.amount
    _sync_paid_status(invoice, actor)
    record(
        actor=actor,
        target=invoice,
        verb=Activity.Verb.PAYMENT_CLEARED,
        changes={
            "payment_id": payment.pk,
            "amount": str(payment.amount),
            "balance_due": str(invoice.balance_due),
        },
    )
    return payment


@transaction.atomic
def bounce_payment(*, payment: Payment, actor) -> Payment:
    """
    PENDING → BOUNCED: the instrument failed. No money ever counted, so
    nothing to roll back — but the row STAYS: a client whose cheques bounce
    is something the next person quoting them deserves to see.
    """
    _check_payment_transition(payment, Payment.Status.BOUNCED)
    payment.status = Payment.Status.BOUNCED
    payment.save(update_fields=["status", "updated_at"])
    record(
        actor=actor,
        target=payment.invoice,
        verb=Activity.Verb.PAYMENT_BOUNCED,
        changes={"payment_id": payment.pk, "amount": str(payment.amount)},
    )
    return payment


def _check_payment_transition(payment: Payment, new_status: str) -> None:
    if new_status not in Payment.ALLOWED_TRANSITIONS[payment.status]:
        raise ValidationError(
            {"detail": f"A {payment.get_status_display().lower()} payment "
                       f"cannot move to {new_status}."}
        )


@transaction.atomic
def delete_payment(*, payment: Payment, actor) -> None:
    """
    Remove a mis-entered receipt. The invoice's money state rolls back to
    whatever the remaining payments add up to — possibly all the way from
    PAID to ISSUED. Both the original entry and this deletion stay on the
    activity trail: the CORRECTION is visible, not silent.

    Two rows are beyond correction: a RECONCILED payment (it has been matched
    to a real statement line — deleting it would make the books disagree with
    the bank) and one with refunds (the refund rows would point at nothing;
    the PROTECT FK backs this up at the DB).
    """
    invoice = Invoice.objects.select_for_update().get(pk=payment.invoice_id)
    if payment.is_reconciled:
        raise ValidationError(
            {"detail": "This payment is reconciled against the bank statement — "
                       "unreconcile it before deleting."}
        )
    if payment.refunds.exists():
        raise ValidationError(
            {"detail": "This payment has refunds against it — delete those first."}
        )
    amount, was_completed = payment.amount, payment.status == Payment.Status.COMPLETED
    payment.delete()
    if was_completed:  # pending/bounced money never counted, so nothing moves
        invoice.amount_paid -= amount
        _sync_paid_status(invoice, actor)
    record(
        actor=actor,
        target=invoice,
        verb=Activity.Verb.PAYMENT_DELETED,
        changes={"amount": str(amount), "balance_due": str(invoice.balance_due)},
    )


# -- refunds ------------------------------------------------------------------


@transaction.atomic
def record_refund(*, payment: Payment, refund: Refund, actor) -> Refund:
    """
    Send money back against one receipt. The cap is per-PAYMENT (you cannot
    return more than that receipt brought in, minus what already went back),
    which also guarantees the invoice-level books can never go negative.
    The invoice's paid status re-derives from the new net — a refund on a
    PAID invoice reopens the balance.
    """
    invoice = Invoice.objects.select_for_update().get(pk=payment.invoice_id)
    if payment.status != Payment.Status.COMPLETED:
        raise ValidationError(
            {"detail": "Only a completed payment can be refunded — this one is "
                       f"{payment.get_status_display().lower()}."}
        )
    if refund.amount > payment.refundable_amount:
        raise ValidationError(
            {"amount": f"Refund exceeds what is refundable on this payment "
                       f"({payment.refundable_amount})."}
        )
    refund.payment = payment
    refund.recorded_by = actor
    refund.save()
    invoice.amount_refunded += refund.amount
    _sync_paid_status(invoice, actor)
    record(
        actor=actor,
        target=invoice,
        verb=Activity.Verb.REFUND_RECORDED,
        changes={
            "refund_id": refund.pk,
            "payment_id": payment.pk,
            "amount": str(refund.amount),
            "reason": refund.reason,
            "balance_due": str(invoice.balance_due),
        },
    )
    return refund


@transaction.atomic
def delete_refund(*, refund: Refund, actor) -> None:
    """Remove a mis-entered refund; the invoice's net and status roll
    forward again. Restores a previously valid state, so no overpay check."""
    invoice = Invoice.objects.select_for_update().get(pk=refund.payment.invoice_id)
    amount = refund.amount
    refund.delete()
    invoice.amount_refunded -= amount
    _sync_paid_status(invoice, actor)
    record(
        actor=actor,
        target=invoice,
        verb=Activity.Verb.REFUND_DELETED,
        changes={"amount": str(amount), "balance_due": str(invoice.balance_due)},
    )


# -- reconciliation -----------------------------------------------------------


@transaction.atomic
def reconcile_payment(*, payment: Payment, actor) -> Payment:
    """
    Tick one receipt off against the bank statement: "I found this exact
    money on the bank's record". Only cleared money can match a statement
    line, and once matched the row is locked against deletion.
    """
    if payment.status != Payment.Status.COMPLETED:
        raise ValidationError(
            {"detail": "Only a completed payment can be reconciled — the bank "
                       "statement can only ever show money that actually moved."}
        )
    if payment.is_reconciled:
        raise ValidationError({"detail": "This payment is already reconciled."})
    payment.reconciled_at = timezone.now()
    payment.reconciled_by = actor
    payment.save(update_fields=["reconciled_at", "reconciled_by", "updated_at"])
    record(
        actor=actor,
        target=payment.invoice,
        verb=Activity.Verb.RECONCILED,
        changes={"payment_id": payment.pk, "reconciled": True},
    )
    return payment


@transaction.atomic
def unreconcile_payment(*, payment: Payment, actor) -> Payment:
    """Undo a wrong match (ticked the wrong row). The trail keeps both moves
    — reconciliation history is evidence, so even its mistakes stay visible."""
    if not payment.is_reconciled:
        raise ValidationError({"detail": "This payment is not reconciled."})
    payment.reconciled_at = None
    payment.reconciled_by = None
    payment.save(update_fields=["reconciled_at", "reconciled_by", "updated_at"])
    record(
        actor=actor,
        target=payment.invoice,
        verb=Activity.Verb.RECONCILED,
        changes={"payment_id": payment.pk, "reconciled": False},
    )
    return payment
