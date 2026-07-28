"""
Client Management models (ARCHITECTURE.md §4, §5 — Phase 2).

Client  = the COMPANY we do business with (the account).
Contact = a PERSON who works at that company (the humans we call/email).

One client has many contacts (1 → N), and later many projects and deals.
Splitting people from companies is basic normalization: if the company's
address were repeated on every person row, fixing a typo would mean updating
N rows and risking disagreement between them.
"""

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex, OpClass
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Upper

from apps.core.models import TimeStampedModel

# Indian GSTIN: 2-digit state code + 10-char PAN + entity digit + "Z" + checksum.
# Format-only check — real verification against the GST portal is an external
# integration, not a field validator's job.
GSTIN_VALIDATOR = RegexValidator(
    regex=r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$",
    message="Enter a valid 15-character GSTIN, e.g. 29ABCDE1234F1Z5.",
)

# Phone: optional "+" then 7–15 digits, with up to two space/dash/bracket
# separator chars between digits — accepts what the form's prefix+number
# input emits ("+91 98765 43210") as well as "(415) 555-0132" and bare
# landlines ("0484-2334455"). Format-only, same philosophy as the GSTIN
# check: no carrier/region lookup. Shared by Client and Contact.
PHONE_VALIDATOR = RegexValidator(
    regex=r"^\+?[0-9](?:[ \-()]{0,2}[0-9]){6,14}$",
    message="Enter a valid phone number, e.g. +91 98765 43210.",
)


class Client(TimeStampedModel):
    """
    A client company (account). Soft-deleted via `is_active` (§4): clients own
    projects, invoices and history — a hard DELETE would orphan or cascade
    away audit data, so "delete" only hides the row from the API.
    """

    class Status(models.TextChoices):
        # Business lifecycle of the RELATIONSHIP — distinct from is_active,
        # which is record lifecycle (deleted or not). An INACTIVE client is
        # still visible; a soft-deleted one is not.
        PROSPECT = "prospect", "Prospect"  # talking, nothing signed yet
        ACTIVE = "active", "Active"  # has ongoing work
        INACTIVE = "inactive", "Inactive"  # past client, kept for history

    # -- identity -----------------------------------------------------------
    name = models.CharField(max_length=150, unique=True)
    industry = models.CharField(max_length=100, blank=True)
    website = models.URLField(blank=True)
    # Company-level coordinates (switchboard / info@) — person-level ones
    # live on Contact.
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True, validators=[PHONE_VALIDATOR])

    # -- tax ----------------------------------------------------------------
    # Optional: foreign or unregistered clients have no GSTIN. blank="" rather
    # than NULL so there is exactly one representation of "absent" (Django
    # convention for strings); uniqueness is enforced only on non-blank values
    # by the conditional constraint below.
    gst_number = models.CharField("GSTIN", max_length=15, blank=True, validators=[GSTIN_VALIDATOR])

    # -- address (embedded, not a separate table — see docs: one address per
    # client today; promote to an Address model only when billing/shipping
    # addresses genuinely diverge) ------------------------------------------
    address_line1 = models.CharField(max_length=255, blank=True)
    address_line2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=100, blank=True, default="India")

    # -- relationship management ---------------------------------------------
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROSPECT)
    # PROTECT (§4): deleting a user who owns clients must fail loudly —
    # reassign their book of business first. SET_NULL would silently orphan
    # accounts; CASCADE would delete clients with the user. null=True because
    # a just-imported client may not have an owner yet.
    account_manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="managed_clients",
    )

    # -- soft delete ----------------------------------------------------------
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            # Two clients may both have gst_number="" (unknown), but a real
            # GSTIN may exist only once.
            models.UniqueConstraint(
                fields=["gst_number"],
                condition=~Q(gst_number=""),
                name="uniq_client_gstin_when_set",
            ),
        ]
        indexes = [
            # The list screen's hottest filter (§4: index the hot filters).
            models.Index(fields=["status", "is_active"]),
            # Global search does a case-insensitive contains-match — only a
            # trigram GIN index can serve one; B-trees need a known prefix.
            # Upper(), not the raw column: Django compiles icontains to
            # UPPER(name) LIKE UPPER(%s), and Postgres only uses an
            # expression index whose expression matches the query EXACTLY
            # (an index on plain "name" is provably dead — EXPLAIN shows a
            # seq scan).
            GinIndex(OpClass(Upper("name"), name="gin_trgm_ops"), name="client_name_trgm"),
        ]

    def __str__(self):
        return self.name


class Contact(TimeStampedModel):
    """
    A person at a client company. CASCADE (§4): contacts have no meaning
    without their company — deleting the client removes its people rows too
    (only reachable if a client is ever hard-deleted; the API soft-deletes).
    """

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="contacts")
    name = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True, validators=[PHONE_VALIDATOR])
    position = models.CharField(max_length=100, blank=True)  # "CTO", "Accounts"
    # Exactly one primary per client, guaranteed by the DB itself — application
    # code alone can't prevent two simultaneous requests both writing True.
    is_primary = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["client"],
                condition=Q(is_primary=True),
                name="uniq_primary_contact_per_client",
            ),
        ]
        indexes = [
            # Global search: people are looked up by partial name (trigram GIN
            # over Upper(), same reasoning as Client.name).
            GinIndex(OpClass(Upper("name"), name="gin_trgm_ops"), name="contact_name_trgm"),
        ]
        ordering = ["-is_primary", "name"]  # primary first, then alphabetical

    def __str__(self):
        return f"{self.name} ({self.client.name})"
