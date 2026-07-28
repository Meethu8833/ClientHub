"""
Quotation Management models (docs/quotations-module.md).

A Quotation is a priced offer sent to a client: line items, discounts, taxes,
a validity window, an internal approval gate, and a client decision. Two
models:

Quotation      the offer's header: who it's for, where it stands in the
               lifecycle, its money totals, its validity and approval trail.
QuotationItem  one priced line ("Backend development — 120 hours × ₹2,000").

Money rules that shape everything here:
- All money is Decimal (§11: never float). Line amounts are rounded to 2
  decimal places (ROUND_HALF_UP — the "commercial" rounding a client's
  accountant expects) and the quote totals are sums of rounded lines, so the
  numbers on screen always add up to the printed total.
- Discount before tax: tax is charged on what the client actually pays
  (GST rules), so per-line discount → quote-level discount → THEN tax.
- Totals are DENORMALIZED onto the quotation (recomputed by services on every
  item write). Stored, not computed per read, because (a) list screens sort
  and filter by grand_total, and (b) once a quote is sent the figures are
  frozen history — they must not drift if tax logic changes in a release.

Lifecycle: a quotation that reached the client is never edited or deleted —
changes happen by REVISING it into a new version row (same quote_number,
version+1). Only never-submitted drafts may be deleted.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db import models
from django.db.models import Q
from django.db.models.functions import Upper

from apps.core.models import TimeStampedModel

TWO_PLACES = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    """Round to 2 decimal places, .005 rounding up — commercial rounding."""
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


class Quotation(TimeStampedModel):
    """
    One version of one offer. Status moves only along ALLOWED_TRANSITIONS and
    only through services.py (same state-machine discipline as Ticket):
    almost every move stamps timestamps or requires input, so a writable
    status field would let callers skip the bookkeeping.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"  # being written; fully editable
        PENDING_APPROVAL = "pending_approval", "Pending approval"  # waiting on a manager
        APPROVED = "approved", "Approved"  # cleared internally, not yet sent
        SENT = "sent", "Sent"  # with the client, clock ticking
        ACCEPTED = "accepted", "Accepted"  # client said yes — terminal
        DECLINED = "declined", "Declined"  # client said no — terminal
        EXPIRED = "expired", "Expired"  # validity ran out — terminal
        CANCELLED = "cancelled", "Cancelled"  # we withdrew it — terminal
        SUPERSEDED = "superseded", "Superseded"  # replaced by a newer version — terminal

    # Which moves are legal FROM each status; anything else is a 400.
    # EXPIRED is entered only by the expiry sweep; SUPERSEDED only by revise().
    ALLOWED_TRANSITIONS = {
        Status.DRAFT: {Status.PENDING_APPROVAL, Status.CANCELLED},
        Status.PENDING_APPROVAL: {Status.APPROVED, Status.DRAFT, Status.CANCELLED},
        Status.APPROVED: {Status.SENT, Status.CANCELLED, Status.SUPERSEDED},
        Status.SENT: {Status.ACCEPTED, Status.DECLINED, Status.EXPIRED, Status.SUPERSEDED},
        Status.ACCEPTED: set(),
        Status.DECLINED: set(),
        Status.EXPIRED: set(),
        Status.CANCELLED: set(),
        Status.SUPERSEDED: set(),
    }

    # Statuses a new version may be cut from. Not ACCEPTED (that's a done
    # deal — new work is a NEW quotation) and not DRAFT/PENDING (just edit it).
    REVISABLE_STATUSES = (Status.APPROVED, Status.SENT, Status.DECLINED, Status.EXPIRED)

    # -- identity ------------------------------------------------------------
    # "QT-2026-0007". Shared by every version of the same offer; the PAIR
    # (quote_number, version) is unique. Assigned once by services, never
    # editable — clients file disputes against this number.
    quote_number = models.CharField(max_length=20, editable=False)
    version = models.PositiveSmallIntegerField(default=1, editable=False)
    # The version this one was cut from. SET_NULL: deleting an old draft
    # revision must not take the chain's newer members with it.
    revision_of = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revisions",
    )

    # -- who it's for ---------------------------------------------------------
    # PROTECT: a client with quotation history can't be hard-deleted (§4).
    client = models.ForeignKey(
        "clients.Client", on_delete=models.PROTECT, related_name="quotations"
    )
    # The person it is addressed to. SET_NULL + optional: the offer outlives
    # the contact record, and some early quotes go to the company generally.
    contact = models.ForeignKey(
        "clients.Contact",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="quotations",
    )
    title = models.CharField(max_length=200)
    # Payment terms, delivery notes — the fine print under the item table.
    terms = models.TextField(blank=True)

    # -- money ----------------------------------------------------------------
    # ISO 4217 code. A plain CharField (not choices): which currencies a shop
    # quotes in is business data, not something that changes with releases.
    currency = models.CharField(max_length=3, default="INR")
    # Quote-level discount, PERCENT ONLY — a percent applies cleanly to every
    # line before tax. (A fixed "₹5,000 off the total" must be allocated
    # across lines with differing tax rates to keep the tax math lawful —
    # deliberately out of scope; see docs.)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))
    # Denormalized totals — services.recompute_totals() is the only writer.
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    discount_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    grand_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))

    # -- lifecycle ------------------------------------------------------------
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    # Last day the offer stands. Optional while drafting, REQUIRED at submit —
    # an open-ended price promise is a liability nobody signs off on.
    valid_until = models.DateField(null=True, blank=True)

    # SET_NULL: quotes outlive their author's account (money history, §4).
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="quotations_created",
    )

    # -- approval trail -------------------------------------------------------
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="quotations_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    # Approve's optional comment OR request-changes' required reason —
    # whichever verdict was given last.
    approval_note = models.CharField(max_length=255, blank=True)

    # -- client-facing trail --------------------------------------------------
    sent_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    declined_at = models.DateTimeField(null=True, blank=True)
    decline_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # One row per (offer, version) — the backbone of versioning.
            models.UniqueConstraint(
                fields=["quote_number", "version"], name="quotation_number_version_unique"
            ),
            models.CheckConstraint(
                condition=Q(discount_percent__gte=0) & Q(discount_percent__lte=100),
                name="quotation_discount_percent_range",
            ),
            # An accepted quote always knows WHEN — dashboards and revenue
            # reports are built on this timestamp, so the DB guards it.
            models.CheckConstraint(
                condition=Q(status="accepted", accepted_at__isnull=False) | ~Q(status="accepted"),
                name="quotation_accepted_has_timestamp",
            ),
        ]
        indexes = [
            # The pipeline screen's hot filters (§4: index list-screen filters).
            models.Index(fields=["status", "created_by"]),
            models.Index(fields=["client", "status"]),
            # The expiry sweep: WHERE status='sent' AND valid_until < today.
            models.Index(fields=["valid_until"]),
            # Global search: partial-title match ("epor" finds "Annual report
            # portal"), Upper() to match icontains. quote_number is NOT
            # trigram-indexed: it's a short prefix-shaped code ("QT-2026-…")
            # a scan serves fine at this table's size.
            GinIndex(OpClass(Upper("title"), name="gin_trgm_ops"), name="quotation_title_trgm"),
        ]

    # A quotation may only be edited (fields, items) while it is a draft.
    @property
    def is_editable(self) -> bool:
        return self.status == self.Status.DRAFT

    @property
    def display_number(self) -> str:
        """What the client sees: 'QT-2026-0007' or 'QT-2026-0007 v2'."""
        if self.version == 1:
            return self.quote_number
        return f"{self.quote_number} v{self.version}"

    @property
    def is_expired(self) -> bool:
        """
        Live check — the sweep runs on a schedule, but the UI (and the accept
        guard) must not honour a lapsed offer in the gap before the sweep.
        """
        from django.utils import timezone

        return (
            self.status == self.Status.SENT
            and self.valid_until is not None
            and self.valid_until < timezone.localdate()
        )

    def __str__(self):
        return f"{self.display_number} — {self.title}"


class QuotationItem(TimeStampedModel):
    """
    One priced line. The line does its own math (self-contained model
    behaviour, §11): every stage of subtotal → discount → tax → total is a
    property, and services sums the lines into the quotation's stored totals.

    Editable only while the parent is a DRAFT — enforced in services/views,
    because "the DB can't know who's asking" but the API layer can.
    """

    # CASCADE: lines are meaningless without their quotation (only reachable
    # when a never-submitted draft is deleted — the only deletable state).
    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name="items")
    description = models.CharField(max_length=255)
    # Decimal quantity: services sell 7.5 hours, not just whole pieces.
    quantity = models.DecimalField(max_digits=8, decimal_places=2)
    # "hours", "pcs", "months" — display text on the printed quote.
    unit = models.CharField(max_length=20, blank=True)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    # Per-line discount, e.g. "20% off the maintenance line only".
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))
    # Per-line tax rate: GST rates differ by service type (18% for IT
    # services today), so the rate lives on the LINE, not the quote.
    tax_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("18"))
    # Manual sort order on the printed quote; defaults to insertion order.
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="quotation_item_qty_positive"),
            models.CheckConstraint(
                condition=Q(unit_price__gte=0), name="quotation_item_price_not_negative"
            ),
            models.CheckConstraint(
                condition=Q(discount_percent__gte=0) & Q(discount_percent__lte=100),
                name="quotation_item_discount_range",
            ),
            models.CheckConstraint(
                condition=Q(tax_percent__gte=0) & Q(tax_percent__lte=100),
                name="quotation_item_tax_range",
            ),
        ]

    # -- the money pipeline, one stage per property ---------------------------

    @property
    def line_subtotal(self) -> Decimal:
        """quantity × unit_price, before anything is taken off."""
        return money(self.quantity * self.unit_price)

    @property
    def line_discount(self) -> Decimal:
        """This line's OWN discount (the quote-level one is applied on top)."""
        return money(self.line_subtotal * self.discount_percent / 100)

    @property
    def taxable_amount(self) -> Decimal:
        """
        What tax is charged on: after the line discount AND the quote-level
        discount. Both come off BEFORE tax — tax law taxes what is actually
        payable, not the list price.
        """
        after_line = self.line_subtotal - self.line_discount
        quote_pct = self.quotation.discount_percent
        return money(after_line * (100 - quote_pct) / 100)

    @property
    def line_tax(self) -> Decimal:
        return money(self.taxable_amount * self.tax_percent / 100)

    @property
    def line_total(self) -> Decimal:
        return self.taxable_amount + self.line_tax

    def __str__(self):
        return f"{self.description} ({self.quantity} × {self.unit_price})"
