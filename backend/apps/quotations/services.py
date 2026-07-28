"""
Side-effectful quotation logic (§11: views stay thin). Numbering, total
recomputation, every status move and the version-cloning all live here —
each function is one atomic unit of "change + its bookkeeping + its history
row", exactly the tickets pattern.

Why status is not `PATCH {"status": ...}`: every transition carries side
effects (submit validates items + validity, approve stamps who/when and
enforces segregation of duties, send freezes the offer, revise clones it).
A writable status field would let callers skip all of that.
"""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.activities.models import Activity
from apps.activities.services import record

from .models import Quotation, QuotationItem

ZERO = Decimal("0.00")


# -- numbering ----------------------------------------------------------------


def _next_quote_number() -> str:
    """
    "QT-<year>-<seq>", sequence restarting each year (QT-2026-0001, -0002…).
    Zero-padded so text ordering == numeric ordering, which lets us find the
    latest with a plain ORDER BY.

    Concurrency: select_for_update() locks the current latest row, making a
    concurrent creator wait; the UniqueConstraint on (quote_number, version)
    is the backstop if both hit an empty year at once. Numbers may end up
    with GAPS (a deleted draft's number is not reused) — that is fine for
    quotes; only tax INVOICES legally require gapless sequences.
    """
    prefix = f"QT-{timezone.localdate().year}-"
    latest = (
        Quotation.objects.select_for_update()
        .filter(quote_number__startswith=prefix)
        .order_by("-quote_number")
        .values_list("quote_number", flat=True)
        .first()
    )
    seq = int(latest.removeprefix(prefix)) + 1 if latest else 1
    return f"{prefix}{seq:04d}"


# -- totals -------------------------------------------------------------------


def recompute_totals(quotation: Quotation) -> Quotation:
    """
    Re-derive the four stored totals from the lines. Called after EVERY write
    that can move money (item add/edit/delete, quote discount change) — the
    stored figures are a cache of the line math, and a cache that isn't
    refreshed on every write is a bug factory.

    Sums are over per-line ROUNDED figures so the printed lines add up to the
    printed total — accountants reconcile line by line.
    """
    # Query the table, NOT quotation.items.all(): the viewset fetches
    # quotations with prefetch_related("items"), and .all() would happily
    # return that stale cache — computing totals that miss the line just added.
    items = list(QuotationItem.objects.filter(quotation=quotation))
    subtotal = sum((i.line_subtotal for i in items), ZERO)
    taxable = sum((i.taxable_amount for i in items), ZERO)
    quotation.subtotal = subtotal
    quotation.discount_total = subtotal - taxable  # line + quote-level discounts combined
    quotation.tax_total = sum((i.line_tax for i in items), ZERO)
    quotation.grand_total = taxable + quotation.tax_total
    quotation.save(
        update_fields=["subtotal", "discount_total", "tax_total", "grand_total", "updated_at"]
    )
    return quotation


# -- guards -------------------------------------------------------------------


def _check_transition(quotation: Quotation, new_status: str) -> None:
    if new_status not in Quotation.ALLOWED_TRANSITIONS[quotation.status]:
        raise ValidationError(
            {
                "status": f"Cannot move a {quotation.get_status_display().lower()} "
                f"quotation to {new_status}."
            }
        )


def _require_draft(quotation: Quotation) -> None:
    """Field/item edits are draft-only — everything after submit is frozen."""
    if not quotation.is_editable:
        raise ValidationError(
            {"detail": "Only a draft can be edited — revise the quotation to make changes."}
        )


def _change_status(quotation: Quotation, new_status: str, actor) -> Quotation:
    """The one gate every move goes through: validate, save, one history row."""
    _check_transition(quotation, new_status)
    old_status = quotation.status
    quotation.status = new_status
    quotation.save()
    record(
        actor=actor,
        target=quotation,
        verb=Activity.Verb.STATUS_CHANGED,
        changes={"field": "status", "from": old_status, "to": new_status},
    )
    return quotation


# -- create / update ----------------------------------------------------------


@transaction.atomic
def create_quotation(*, quotation: Quotation, actor) -> Quotation:
    """Persist a new draft: assign its number, stamp the author, open history."""
    quotation.quote_number = _next_quote_number()
    quotation.created_by = actor
    quotation.save()
    record(actor=actor, target=quotation, verb=Activity.Verb.CREATED, changes={})
    return quotation


@transaction.atomic
def update_quotation(*, quotation: Quotation, actor) -> Quotation:
    """
    Persist draft field edits. Totals are recomputed because discount_percent
    may be among the edits; one UPDATED row keeps the audit trail honest.
    """
    _require_draft(quotation)
    quotation.save()
    recompute_totals(quotation)
    record(actor=actor, target=quotation, verb=Activity.Verb.UPDATED, changes={})
    return quotation


# -- items --------------------------------------------------------------------


@transaction.atomic
def add_item(*, quotation: Quotation, item: QuotationItem, actor) -> QuotationItem:
    _require_draft(quotation)
    item.quotation = quotation
    if not item.position:  # default: append to the end of the printed table
        last = quotation.items.order_by("-position").first()
        item.position = (last.position + 1) if last else 1
    item.save()
    recompute_totals(quotation)
    record(
        actor=actor,
        target=quotation,
        verb=Activity.Verb.UPDATED,
        changes={"item_added": item.description},
    )
    return item


@transaction.atomic
def update_item(*, item: QuotationItem, actor) -> QuotationItem:
    _require_draft(item.quotation)
    item.save()
    recompute_totals(item.quotation)
    record(
        actor=actor,
        target=item.quotation,
        verb=Activity.Verb.UPDATED,
        changes={"item_updated": item.description},
    )
    return item


@transaction.atomic
def delete_item(*, item: QuotationItem, actor) -> None:
    _require_draft(item.quotation)
    quotation, description = item.quotation, item.description
    item.delete()
    recompute_totals(quotation)
    record(
        actor=actor,
        target=quotation,
        verb=Activity.Verb.UPDATED,
        changes={"item_removed": description},
    )


# -- lifecycle ----------------------------------------------------------------


@transaction.atomic
def submit_quotation(*, quotation: Quotation, actor) -> Quotation:
    """
    Draft → pending approval. The completeness gate lives HERE, not at
    approve/send: a reviewer's time is only spent on offers that are actually
    reviewable (priced lines + an expiry date that is still in the future).
    """
    if not quotation.items.exists():
        raise ValidationError({"detail": "Add at least one line item before submitting."})
    if quotation.valid_until is None:
        raise ValidationError({"valid_until": "Set a validity date before submitting."})
    if quotation.valid_until < timezone.localdate():
        raise ValidationError({"valid_until": "The validity date is already in the past."})
    quotation.submitted_at = timezone.now()
    return _change_status(quotation, Quotation.Status.PENDING_APPROVAL, actor)


@transaction.atomic
def approve_quotation(*, quotation: Quotation, actor, note: str = "") -> Quotation:
    """
    Manager sign-off. Segregation of duties: the author may not approve their
    own offer — the entire point of the gate is a SECOND pair of eyes on the
    numbers before a client sees them.
    """
    if actor == quotation.created_by:
        raise ValidationError({"detail": "You cannot approve your own quotation."})
    quotation.approved_by = actor
    quotation.approved_at = timezone.now()
    quotation.approval_note = note
    return _change_status(quotation, Quotation.Status.APPROVED, actor)


@transaction.atomic
def request_changes(*, quotation: Quotation, actor, note: str) -> Quotation:
    """
    Reviewer bounces it back to draft. The note is REQUIRED — "no" without
    "why" leaves the author guessing and the next reviewer context-free.
    """
    quotation.approval_note = note
    return _change_status(quotation, Quotation.Status.DRAFT, actor)


@transaction.atomic
def send_quotation(*, quotation: Quotation, actor) -> Quotation:
    """
    Mark the offer as delivered to the client. Re-checks validity: an
    approved quote can sit in a drawer past its own expiry date.
    """
    if quotation.valid_until < timezone.localdate():
        raise ValidationError(
            {"valid_until": "The validity date has passed — revise the quotation first."}
        )
    quotation.sent_at = timezone.now()
    return _change_status(quotation, Quotation.Status.SENT, actor)


@transaction.atomic
def accept_quotation(*, quotation: Quotation, actor) -> Quotation:
    """
    Record the client's yes. A lapsed offer cannot be accepted even if the
    nightly sweep hasn't flagged it yet — the promise ended at midnight, not
    at the next cron run.
    """
    if quotation.is_expired:
        raise ValidationError(
            {"detail": "This quotation has expired — revise it to make a fresh offer."}
        )
    quotation.accepted_at = timezone.now()
    return _change_status(quotation, Quotation.Status.ACCEPTED, actor)


@transaction.atomic
def decline_quotation(*, quotation: Quotation, actor, reason: str = "") -> Quotation:
    """Record the client's no. The reason feeds the win/loss report."""
    quotation.declined_at = timezone.now()
    quotation.decline_reason = reason
    return _change_status(quotation, Quotation.Status.DECLINED, actor)


@transaction.atomic
def cancel_quotation(*, quotation: Quotation, actor) -> Quotation:
    """Withdraw an offer that never reached (or never got past) the client."""
    return _change_status(quotation, Quotation.Status.CANCELLED, actor)


@transaction.atomic
def expire_quotation(*, quotation: Quotation) -> Quotation:
    """Sweep-only path (actor=None = the system), used by expire_quotations."""
    return _change_status(quotation, Quotation.Status.EXPIRED, None)


# -- versioning ---------------------------------------------------------------


@transaction.atomic
def revise_quotation(*, quotation: Quotation, actor) -> Quotation:
    """
    Cut version N+1: a fresh DRAFT with the same quote_number, cloned header
    fields and cloned lines, linked back via revision_of. The old version is
    left as the record of what the client was actually shown:

    - APPROVED / SENT (still "live") → SUPERSEDED, so exactly one version of
      an offer is ever active;
    - DECLINED / EXPIRED keep their status — "the client declined v1" is
      history, and history doesn't change because we tried again.

    Editing-in-place is forbidden for anything past draft, so this is the
    ONLY way a delivered offer ever changes.
    """
    if quotation.status not in Quotation.REVISABLE_STATUSES:
        raise ValidationError(
            {"detail": f"A {quotation.get_status_display().lower()} quotation cannot be revised."}
        )
    if quotation.revisions.exists():
        raise ValidationError({"detail": "This version has already been revised."})

    new = Quotation.objects.create(
        quote_number=quotation.quote_number,
        version=quotation.version + 1,
        revision_of=quotation,
        client=quotation.client,
        contact=quotation.contact,
        title=quotation.title,
        terms=quotation.terms,
        currency=quotation.currency,
        discount_percent=quotation.discount_percent,
        valid_until=None,  # a new offer needs a freshly chosen validity window
        created_by=actor,
    )
    for item in quotation.items.all():
        QuotationItem.objects.create(
            quotation=new,
            description=item.description,
            quantity=item.quantity,
            unit=item.unit,
            unit_price=item.unit_price,
            discount_percent=item.discount_percent,
            tax_percent=item.tax_percent,
            position=item.position,
        )
    recompute_totals(new)
    record(
        actor=actor,
        target=new,
        verb=Activity.Verb.CREATED,
        changes={"revised_from": quotation.pk, "version": new.version},
    )
    if quotation.status in (Quotation.Status.APPROVED, Quotation.Status.SENT):
        _change_status(quotation, Quotation.Status.SUPERSEDED, actor)
    return new
