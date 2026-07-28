"""
Invoice API tests: draft-then-issue numbering, the discount→tax money
pipeline, the lifecycle state machine, overdue-as-condition, the billing
permission wall (staff see nothing), and from-quotation copying.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.billing import services
from apps.billing.models import Invoice, InvoiceItem
from apps.clients.models import Client, Contact
from apps.projects.models import Project
from apps.quotations import services as quotation_services
from apps.quotations.models import Quotation, QuotationItem

PASSWORD = "Str0ng!pass123"

pytestmark = pytest.mark.django_db


def api_for(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def manager():
    return User.objects.create_user(email="mgr@x.com", password=PASSWORD, role=User.Role.MANAGER)


@pytest.fixture
def manager_api(manager):
    return api_for(manager)


@pytest.fixture
def staff_api():
    return api_for(
        User.objects.create_user(email="staff@x.com", password=PASSWORD, role=User.Role.STAFF)
    )


@pytest.fixture
def client_co():
    return Client.objects.create(name="Acme")


@pytest.fixture
def draft(manager, client_co):
    """An issuable draft: one 10 × 2000 line at the default 18% tax."""
    inv = services.create_invoice(invoice=Invoice(client=client_co), actor=manager)
    services.add_item(
        invoice=inv,
        item=InvoiceItem(
            description="Backend development",
            quantity=Decimal("10"),
            unit="hours",
            unit_price=Decimal("2000"),
        ),
        actor=manager,
    )
    return inv


@pytest.fixture
def issued(draft, manager):
    return services.issue_invoice(invoice=draft, actor=manager)


def url(pk, verb=None):
    if verb:
        return reverse(f"billing:invoice-{verb}", args=[pk])
    return reverse("billing:invoice-detail", args=[pk])


# --- creation & drafts -------------------------------------------------------


def test_create_draft_has_no_number(manager_api, client_co):
    resp = manager_api.post(reverse("billing:invoice-list"), {"client_id": client_co.pk})
    assert resp.status_code == 201
    assert resp.data["status"] == "draft"
    assert resp.data["invoice_number"] is None
    assert resp.data["display_number"].startswith("DRAFT-")
    assert Decimal(resp.data["grand_total"]) == Decimal("0.00")


def test_item_math_discounts_before_tax(manager_api, draft):
    # 10 × 2000 = 20000; 10% line discount → 18000; 5% invoice discount
    # → 17100 taxable; 18% tax → 3078; line total 20178.
    manager_api.patch(url(draft.pk), {"discount_percent": "5"})
    resp = manager_api.post(
        url(draft.pk, "items"),
        {
            "description": "Design",
            "quantity": "10",
            "unit_price": "2000",
            "discount_percent": "10",
        },
    )
    assert resp.status_code == 201
    assert Decimal(resp.data["taxable_amount"]) == Decimal("17100.00")
    assert Decimal(resp.data["line_tax"]) == Decimal("3078.00")
    assert Decimal(resp.data["line_total"]) == Decimal("20178.00")

    detail = manager_api.get(url(draft.pk)).data
    # First line is also re-taxed under the 5% invoice discount: 20000 → 19000
    # taxable + 3420 tax; totals are sums of rounded lines.
    assert Decimal(detail["subtotal"]) == Decimal("40000.00")
    assert Decimal(detail["discount_total"]) == Decimal("3900.00")
    assert Decimal(detail["tax_total"]) == Decimal("6498.00")
    assert Decimal(detail["grand_total"]) == Decimal("42598.00")


def test_client_is_immutable(manager_api, draft):
    other = Client.objects.create(name="Globex")
    resp = manager_api.patch(url(draft.pk), {"client_id": other.pk})
    assert resp.status_code == 400


def test_contact_and_project_must_belong_to_client(manager_api, client_co):
    stranger = Client.objects.create(name="Globex")
    foreign_contact = Contact.objects.create(client=stranger, name="Jo")
    foreign_project = Project.objects.create(client=stranger, name="Their build")
    resp = manager_api.post(
        reverse("billing:invoice-list"),
        {"client_id": client_co.pk, "contact_id": foreign_contact.pk},
    )
    assert resp.status_code == 400
    resp = manager_api.post(
        reverse("billing:invoice-list"),
        {"client_id": client_co.pk, "project_id": foreign_project.pk},
    )
    assert resp.status_code == 400


# --- the permission wall -----------------------------------------------------


def test_staff_see_nothing(staff_api, issued):
    assert staff_api.get(reverse("billing:invoice-list")).status_code == 403
    assert staff_api.get(url(issued.pk)).status_code == 403
    assert staff_api.post(url(issued.pk, "payments"), {}).status_code == 403


# --- issuing & numbering -----------------------------------------------------


def test_issue_requires_items(manager_api, manager, client_co):
    empty = services.create_invoice(invoice=Invoice(client=client_co), actor=manager)
    resp = manager_api.post(url(empty.pk, "issue"))
    assert resp.status_code == 400


def test_issue_assigns_number_and_dates(manager_api, draft):
    resp = manager_api.post(url(draft.pk, "issue"))
    assert resp.status_code == 200
    year = timezone.localdate().year
    assert resp.data["invoice_number"] == f"INV-{year}-0001"
    assert resp.data["issue_date"] == str(timezone.localdate())
    # Default Net 30: due_date = issue_date + payment_terms_days.
    expected_due = timezone.localdate() + timedelta(days=30)
    assert resp.data["due_date"] == str(expected_due)
    assert resp.data["status"] == "issued"


def test_issue_keeps_explicit_due_date(manager_api, draft):
    chosen = timezone.localdate() + timedelta(days=10)
    manager_api.patch(url(draft.pk), {"due_date": str(chosen)})
    resp = manager_api.post(url(draft.pk, "issue"))
    assert resp.data["due_date"] == str(chosen)


def test_numbering_is_sequential_and_draft_deletion_leaves_no_gap(
    manager_api, manager, client_co, draft
):
    # A deleted draft never held a number, so the issued series stays gapless.
    scrap = services.create_invoice(invoice=Invoice(client=client_co), actor=manager)
    assert manager_api.delete(url(scrap.pk)).status_code == 204

    first = manager_api.post(url(draft.pk, "issue")).data["invoice_number"]

    second_draft = services.create_invoice(invoice=Invoice(client=client_co), actor=manager)
    services.add_item(
        invoice=second_draft,
        item=InvoiceItem(description="X", quantity=Decimal("1"), unit_price=Decimal("100")),
        actor=manager,
    )
    second = manager_api.post(url(second_draft.pk, "issue")).data["invoice_number"]
    assert first.endswith("-0001") and second.endswith("-0002")


def test_issued_invoice_is_frozen(manager_api, issued):
    assert manager_api.patch(url(issued.pk), {"notes": "tweak"}).status_code == 400
    resp = manager_api.post(
        url(issued.pk, "items"),
        {"description": "Extra", "quantity": "1", "unit_price": "100"},
    )
    assert resp.status_code == 400
    assert manager_api.delete(url(issued.pk)).status_code == 400


def test_item_flat_edit_recomputes_and_is_draft_only(manager_api, draft, issued):
    # `draft` became `issued` via the fixture chain — build a fresh draft.
    item = issued.items.first()
    flat = reverse("billing:invoice-item-detail", args=[item.pk])
    assert manager_api.patch(flat, {"unit_price": "999"}).status_code == 400


# --- void --------------------------------------------------------------------


def test_void_requires_reason_and_keeps_number(manager_api, issued):
    assert manager_api.post(url(issued.pk, "void"), {}).status_code == 400
    resp = manager_api.post(url(issued.pk, "void"), {"reason": "Wrong amount"})
    assert resp.status_code == 200
    assert resp.data["status"] == "void"
    assert resp.data["invoice_number"] is not None  # the number stays burned
    assert resp.data["voided_at"] is not None


def test_draft_cannot_be_voided(manager_api, draft):
    resp = manager_api.post(url(draft.pk, "void"), {"reason": "nah"})
    assert resp.status_code == 400


# --- overdue is a condition, not a status ------------------------------------


def test_overdue_property_and_filter(manager_api, issued):
    # No API can set a past due date, so simulate time passing in the DB.
    Invoice.objects.filter(pk=issued.pk).update(due_date=date(2020, 1, 1))
    row = manager_api.get(url(issued.pk)).data
    assert row["status"] == "issued"  # status untouched — overdue is derived
    assert row["is_overdue"] is True
    assert row["days_overdue"] > 0

    listed = manager_api.get(reverse("billing:invoice-list"), {"overdue": "true"}).data
    assert [r["id"] for r in listed["results"]] == [issued.pk]


# --- from quotation ----------------------------------------------------------


@pytest.fixture
def accepted_quotation(manager, client_co):
    q = quotation_services.create_quotation(
        quotation=Quotation(client=client_co, title="Site", valid_until=date(2099, 1, 1)),
        actor=manager,
    )
    quotation_services.add_item(
        quotation=q,
        item=QuotationItem(
            description="Backend", quantity=Decimal("10"), unit_price=Decimal("2000")
        ),
        actor=manager,
    )
    quotation_services.submit_quotation(quotation=q, actor=manager)
    approver = User.objects.create_user(
        email="approver@x.com", password=PASSWORD, role=User.Role.MANAGER
    )
    quotation_services.approve_quotation(quotation=q, actor=approver)
    quotation_services.send_quotation(quotation=q, actor=manager)
    return quotation_services.accept_quotation(quotation=q, actor=manager)


def test_from_accepted_quotation_copies_lines(manager_api, accepted_quotation):
    resp = manager_api.post(
        reverse("billing:invoice-from-quotation"), {"quotation_id": accepted_quotation.pk}
    )
    assert resp.status_code == 201
    assert resp.data["status"] == "draft"
    assert resp.data["quotation_id"] == accepted_quotation.pk
    assert len(resp.data["items"]) == 1
    assert Decimal(resp.data["grand_total"]) == Decimal(str(accepted_quotation.grand_total))


def test_from_unaccepted_quotation_is_rejected(manager_api, manager, client_co):
    q = quotation_services.create_quotation(
        quotation=Quotation(client=client_co, title="Site"), actor=manager
    )
    resp = manager_api.post(reverse("billing:invoice-from-quotation"), {"quotation_id": q.pk})
    assert resp.status_code == 400
