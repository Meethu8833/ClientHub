"""
Billing models (docs/billing-module.md, docs/payments-module.md):
Invoice, InvoiceItem, Payment, Refund.

A quotation is an OFFER ("we could do this for ₹X"); an invoice is a DEMAND
("you owe us ₹X by this date"). That difference drives every design choice:

- Numbering happens at ISSUE, not at creation. Indian GST rules (and most tax
  law) require invoice numbers to be a consecutive, gapless series. Drafts can
  be deleted; if drafts held numbers, deleting one would tear a hole in the
  sequence. So a draft has NO number, and an issued invoice can never be
  deleted — only VOIDED, which keeps its number in the books.
- Payment state is DERIVED, never typed in. `amount_paid` is the sum of the
  Payment rows, and issued/partially_paid/paid follows from comparing it to
  grand_total. Nobody can "mark it paid" without the money being recorded.
- OVERDUE is a condition, not a status (same call as ticket escalation):
  it is purely `due_date < today` while money is owed. Making it a status
  would need a cron to set it AND logic to un-set it on payment — a property
  plus a filter gives the same truth with no moving parts.

The item-line money pipeline (discount before tax, per-line rounding, stored
totals) is identical to quotations — same laws, same math, same reasons.
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


class Invoice(TimeStampedModel):
    """
    One bill to one client. Status moves only through services.py:
    issue() assigns the legal number and the due date, record_payment() /
    delete_payment() move the paid states, void() retires a mistake.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"  # being written; editable, deletable, no number
        ISSUED = "issued", "Issued"  # numbered and delivered; money is now owed
        PARTIALLY_PAID = "partially_paid", "Partially paid"  # some money in, balance open
        PAID = "paid", "Paid"  # balance is zero — the good ending
        VOID = "void", "Void"  # cancelled after issue; number stays burned

    # The paid states move in BOTH directions because deleting a mis-entered
    # payment must roll the status back; VOID is terminal.
    ALLOWED_TRANSITIONS = {
        Status.DRAFT: {Status.ISSUED},
        Status.ISSUED: {Status.PARTIALLY_PAID, Status.PAID, Status.VOID},
        Status.PARTIALLY_PAID: {Status.PAID, Status.ISSUED},
        Status.PAID: {Status.PARTIALLY_PAID, Status.ISSUED},
        Status.VOID: set(),
    }

    # Statuses in which money is still owed — the overdue check applies here.
    OWING_STATUSES = (Status.ISSUED, Status.PARTIALLY_PAID)

    # -- identity ------------------------------------------------------------
    # "INV-2026-0042". NULL while draft — assigned once at issue and gapless
    # from then on (issued invoices are never deleted). null=True on a
    # CharField is deliberate here: blank "" would collide in the unique
    # constraint; NULLs never collide.
    invoice_number = models.CharField(  # noqa: DJ001 — NULL ≠ "": see comment above
        max_length=20, null=True, blank=True, editable=False
    )

    # -- who owes -------------------------------------------------------------
    # PROTECT: a client that has been billed can't be hard-deleted (§4).
    client = models.ForeignKey(
        "clients.Client", on_delete=models.PROTECT, related_name="invoices"
    )
    # The billing contact. SET_NULL: the invoice outlives the person's record.
    contact = models.ForeignKey(
        "clients.Contact",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
    )
    # What the bill is for (ERD: INVOICE }o--o| PROJECT). PROTECT, not
    # SET_NULL: an invoice that forgets which project it billed is a hole in
    # the accounts — and projects are soft-deleted anyway.
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="invoices",
    )
    # The accepted offer this bill fulfils, when there is one. SET_NULL and
    # NOT unique: half-upfront/half-on-delivery means several invoices may
    # legitimately point at one quotation.
    quotation = models.ForeignKey(
        "quotations.Quotation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
    )

    # -- money ----------------------------------------------------------------
    currency = models.CharField(max_length=3, default="INR")
    # Invoice-level discount, percent only — same allocation reasoning as
    # quotations (a fixed amount can't be split lawfully across tax rates).
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))
    # Denormalized totals — services.recompute_totals() is the only writer.
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    discount_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    grand_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    # Sum of the COMPLETED Payment rows (gross money in), cached here so list
    # screens can show/filter balances without joining payments. services
    # keeps it in sync. Pending/bounced payments never count.
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    # Sum of the Refund rows (money out again). Kept SEPARATE from amount_paid
    # on purpose: "received ₹23,600, refunded ₹5,000" are two facts a finance
    # screen must show individually — netting them into one column would
    # destroy the gross figure the books need.
    amount_refunded = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))

    # -- dates & terms --------------------------------------------------------
    # "Net 30": how many days after issue the money is due. Used to compute
    # due_date at issue time if one wasn't set explicitly.
    payment_terms_days = models.PositiveSmallIntegerField(default=30)
    # Stamped at issue (not creation): the clock starts when the client
    # actually receives a demand, not when we started drafting it.
    issue_date = models.DateField(null=True, blank=True, editable=False)
    due_date = models.DateField(null=True, blank=True)

    # Printed fine print (bank details, late-fee terms) vs internal-only notes.
    terms = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    # -- lifecycle ------------------------------------------------------------
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)

    # SET_NULL: invoices outlive their author's account (money history, §4).
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="invoices_created",
    )

    # -- trail ----------------------------------------------------------------
    issued_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)  # cleared if a payment is deleted
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Unique only when set — every draft's NULL happily coexists.
            models.UniqueConstraint(
                fields=["invoice_number"],
                condition=Q(invoice_number__isnull=False),
                name="invoice_number_unique",
            ),
            models.CheckConstraint(
                condition=Q(discount_percent__gte=0) & Q(discount_percent__lte=100),
                name="invoice_discount_percent_range",
            ),
            models.CheckConstraint(
                condition=Q(amount_paid__gte=0), name="invoice_amount_paid_not_negative"
            ),
            models.CheckConstraint(
                condition=Q(amount_refunded__gte=0), name="invoice_amount_refunded_not_negative"
            ),
            # An issued invoice always carries its legal identity and dates —
            # the DB guards what the tax office will ask for.
            models.CheckConstraint(
                condition=Q(status="draft")
                | (
                    Q(invoice_number__isnull=False)
                    & Q(issue_date__isnull=False)
                    & Q(due_date__isnull=False)
                ),
                name="invoice_issued_has_number_and_dates",
            ),
            models.CheckConstraint(
                condition=Q(status="paid", paid_at__isnull=False) | ~Q(status="paid"),
                name="invoice_paid_has_timestamp",
            ),
            models.CheckConstraint(
                condition=Q(status="void", voided_at__isnull=False) | ~Q(status="void"),
                name="invoice_void_has_timestamp",
            ),
        ]
        indexes = [
            # The billing screen's hot filters (§4: index list-screen filters).
            models.Index(fields=["status", "client"]),
            # The overdue check: WHERE status IN (owing) AND due_date < today.
            models.Index(fields=["due_date"]),
            # Global search: "0042" should find INV-2026-0042 — a middle-of-
            # string match only a trigram index can serve (Upper() to match
            # what icontains compiles to).
            GinIndex(
                OpClass(Upper("invoice_number"), name="gin_trgm_ops"),
                name="invoice_number_trgm",
            ),
        ]

    # An invoice may only be edited (fields, items) while it is a draft.
    @property
    def is_editable(self) -> bool:
        return self.status == self.Status.DRAFT

    @property
    def display_number(self) -> str:
        """'INV-2026-0042', or a stand-in for drafts that have no number yet."""
        return self.invoice_number or f"DRAFT-{self.pk}"

    @property
    def net_paid(self) -> Decimal:
        """Money we actually HOLD: cleared receipts minus what went back out.
        This — not gross amount_paid — is what the paid status derives from."""
        return self.amount_paid - self.amount_refunded

    @property
    def balance_due(self) -> Decimal:
        """What is still owed right now — THE number a billing screen shows.
        A refund reopens the balance: refund money and the client owes again."""
        return self.grand_total - self.net_paid

    @property
    def is_overdue(self) -> bool:
        """Live check — money owed and the due date behind us. No cron: this
        is derived truth, computed the moment anyone asks."""
        from django.utils import timezone

        return (
            self.status in self.OWING_STATUSES
            and self.due_date is not None
            and self.due_date < timezone.localdate()
        )

    @property
    def days_overdue(self) -> int:
        """For dunning screens: 0 unless overdue."""
        from django.utils import timezone

        if not self.is_overdue:
            return 0
        return (timezone.localdate() - self.due_date).days

    def __str__(self):
        return f"{self.display_number} — {self.client}"


class InvoiceItem(TimeStampedModel):
    """
    One billed line — the same self-computing money pipeline as QuotationItem
    (subtotal → line discount → invoice discount → tax), duplicated rather
    than shared because the two documents freeze at different moments and
    must be free to evolve apart (quotes may get fixed discounts some day;
    invoice math is bound to tax law).

    Editable only while the parent is a DRAFT — enforced in services.
    """

    # CASCADE: lines die with their invoice, and only unnumbered drafts are
    # ever deletable, so no issued line can be lost this way.
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="items")
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=8, decimal_places=2)
    unit = models.CharField(max_length=20, blank=True)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))
    # Tax rate lives on the LINE: one invoice can mix 18% services with
    # 0%-rated or exempt lines.
    tax_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("18"))
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="invoice_item_qty_positive"),
            models.CheckConstraint(
                condition=Q(unit_price__gte=0), name="invoice_item_price_not_negative"
            ),
            models.CheckConstraint(
                condition=Q(discount_percent__gte=0) & Q(discount_percent__lte=100),
                name="invoice_item_discount_range",
            ),
            models.CheckConstraint(
                condition=Q(tax_percent__gte=0) & Q(tax_percent__lte=100),
                name="invoice_item_tax_range",
            ),
        ]

    # -- the money pipeline, one stage per property ---------------------------

    @property
    def line_subtotal(self) -> Decimal:
        """quantity × unit_price, before anything is taken off."""
        return money(self.quantity * self.unit_price)

    @property
    def line_discount(self) -> Decimal:
        return money(self.line_subtotal * self.discount_percent / 100)

    @property
    def taxable_amount(self) -> Decimal:
        """After the line discount AND the invoice-level discount — tax is
        charged on what is actually payable, not the list price."""
        after_line = self.line_subtotal - self.line_discount
        invoice_pct = self.invoice.discount_percent
        return money(after_line * (100 - invoice_pct) / 100)

    @property
    def line_tax(self) -> Decimal:
        return money(self.taxable_amount * self.tax_percent / 100)

    @property
    def line_total(self) -> Decimal:
        return self.taxable_amount + self.line_tax

    def __str__(self):
        return f"{self.description} ({self.quantity} × {self.unit_price})"


class Payment(TimeStampedModel):
    """
    One receipt of money against one invoice — with a small lifecycle of its
    own, because "the client handed us a cheque" and "the bank credited us"
    are different moments and only the second one is money:

        pending ──clear──▶ completed        (counts toward amount_paid)
           └────bounce───▶ bounced          (terminal; never counted)

    Instant methods (UPI, cash, transfer you can see on the statement) are
    recorded COMPLETED directly; a cheque in hand is recorded PENDING.
    Only COMPLETED payments move the invoice's amount_paid / status.

    Append-then-correct still holds: payments are never EDITED (a receipt is
    a fact), but a mis-entry may be DELETED by a manager — services then
    re-derives amount_paid and status, and the Activity trail keeps both the
    entry and the deletion on record. A BOUNCED payment is deliberately NOT
    deleted: the bounce itself is a fact worth keeping (client risk history).

    Reconciliation: `reconciled_at`/`reconciled_by` stamp that this row was
    matched against a real bank-statement line. A reconciled payment is
    LOCKED — it can no longer be deleted, because it has been confirmed to
    exist in the outside world.
    """

    class Method(models.TextChoices):
        BANK_TRANSFER = "bank_transfer", "Bank transfer"
        UPI = "upi", "UPI"
        CARD = "card", "Card"
        CHEQUE = "cheque", "Cheque"
        CASH = "cash", "Cash"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"  # instrument received, money not yet ours
        COMPLETED = "completed", "Completed"  # money confirmed in — the only real state
        BOUNCED = "bounced", "Bounced"  # instrument failed; kept on record

    # pending resolves one way or the other; completed/bounced are final.
    # (A mis-marked COMPLETED payment is corrected by delete + re-enter, not
    # by a transition — the correction must show as two trail entries.)
    ALLOWED_TRANSITIONS = {
        Status.PENDING: {Status.COMPLETED, Status.BOUNCED},
        Status.COMPLETED: set(),
        Status.BOUNCED: set(),
    }

    # PROTECT: an invoice holding real-money records must never vanish, even
    # by accident in a shell — belt to the "only drafts are deletable" braces.
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    # The day the money arrived (bank statement date) — NOT when someone got
    # around to typing it in; created_at records that separately.
    received_on = models.DateField()
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.BANK_TRANSFER)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.COMPLETED)
    # UTR number, cheque number, gateway id — how to find it on a statement.
    reference = models.CharField(max_length=100, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    # SET_NULL: the receipt outlives the clerk's account.
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="payments_recorded",
    )
    # -- reconciliation stamps (null = not yet matched to the statement) ------
    reconciled_at = models.DateTimeField(null=True, blank=True)
    reconciled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments_reconciled",
    )

    class Meta:
        ordering = ["-received_on", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_positive"),
            # Only real money can be ticked off against a statement — the DB
            # refuses a reconciled pending/bounced row no matter who writes it.
            models.CheckConstraint(
                condition=Q(status="completed") | Q(reconciled_at__isnull=True),
                name="payment_reconciled_only_when_completed",
            ),
        ]
        indexes = [
            # "all payments on invoice 7" and date-range cash reports.
            models.Index(fields=["invoice", "-received_on"]),
            # The reconciliation screen: completed rows in a date range,
            # unmatched first.
            models.Index(fields=["status", "received_on"]),
        ]

    @property
    def is_reconciled(self) -> bool:
        return self.reconciled_at is not None

    @property
    def amount_refunded(self) -> Decimal:
        """Total already sent back from THIS receipt. Uses .all() so a
        prefetched queryset is reused instead of re-queried per row."""
        return sum((r.amount for r in self.refunds.all()), Decimal("0.00"))

    @property
    def refundable_amount(self) -> Decimal:
        """How much of this receipt could still go back. Zero unless the
        money actually arrived — you cannot refund a hope or a bounce."""
        if self.status != self.Status.COMPLETED:
            return Decimal("0.00")
        return self.amount - self.amount_refunded

    def __str__(self):
        return f"{self.amount} on {self.invoice} ({self.received_on})"


class Refund(TimeStampedModel):
    """
    Money deliberately sent BACK to the client — the mirror image of a
    Payment, and a different thing from deleting one:

        delete Payment  =  "that receipt never happened" (data correction)
        Refund          =  "it happened, and then we returned the money"
                           (a real second money movement, with its own date,
                           reference and reason — both stay in the books)

    A refund hangs off the PAYMENT it returns (not the invoice directly): the
    money goes back the way it came, and the cap "you cannot return more than
    that receipt brought in" falls out naturally. PROTECT on the FK means a
    payment with refunds can never be deleted — the refund would dangle.

    Same append-then-correct discipline as Payment: no edits, delete-only for
    mis-entries, every move on the Activity trail.
    """

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    # The day the money left us — the refund's own statement date.
    refunded_on = models.DateField()
    method = models.CharField(
        max_length=20, choices=Payment.Method.choices, default=Payment.Method.BANK_TRANSFER
    )
    # The OUTGOING transaction's id — a refund appears on the statement too.
    reference = models.CharField(max_length=100, blank=True)
    # Mandatory (enforced in the serializer): money leaving the company
    # without a written why is an audit red flag, same rule as void_reason.
    reason = models.CharField(max_length=255)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="refunds_recorded",
    )

    class Meta:
        ordering = ["-refunded_on", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="refund_amount_positive"),
        ]

    def __str__(self):
        return f"-{self.amount} on {self.payment} ({self.refunded_on})"
