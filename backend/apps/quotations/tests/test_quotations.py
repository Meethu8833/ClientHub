"""
Quotation API tests: numbering, the discount→tax money pipeline, the
lifecycle state machine + per-role approval boundaries, and draft-only edits.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.activities.models import Activity
from apps.clients.models import Client, Contact
from apps.quotations import services
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
def other_manager_api():
    return api_for(
        User.objects.create_user(email="mgr2@x.com", password=PASSWORD, role=User.Role.MANAGER)
    )


@pytest.fixture
def staff():
    return User.objects.create_user(email="staff@x.com", password=PASSWORD, role=User.Role.STAFF)


@pytest.fixture
def staff_api(staff):
    return api_for(staff)


@pytest.fixture
def client_co():
    return Client.objects.create(name="Acme")


@pytest.fixture
def draft(manager, client_co):
    """A submittable draft: one line, validity set, owned by `manager`."""
    q = services.create_quotation(
        quotation=Quotation(client=client_co, title="Website revamp", valid_until=date(2099, 1, 1)),
        actor=manager,
    )
    services.add_item(
        quotation=q,
        item=QuotationItem(
            description="Backend development",
            quantity=Decimal("10"),
            unit="hours",
            unit_price=Decimal("2000"),
        ),
        actor=manager,
    )
    return q


def url(pk, verb=None):
    if verb:
        return reverse(f"quotations:quotation-{verb}", args=[pk])
    return reverse("quotations:quotation-detail", args=[pk])


# --- creation & numbering ----------------------------------------------------


def test_create_assigns_sequential_yearly_number(manager_api, client_co):
    first = manager_api.post(
        reverse("quotations:quotation-list"), {"client_id": client_co.pk, "title": "A"}
    )
    second = manager_api.post(
        reverse("quotations:quotation-list"), {"client_id": client_co.pk, "title": "B"}
    )
    assert first.status_code == second.status_code == 201
    n1, n2 = first.data["quote_number"], second.data["quote_number"]
    assert n1.startswith("QT-") and n1.endswith("-0001")
    assert n2.endswith("-0002")
    assert first.data["status"] == "draft"


def test_contact_must_belong_to_client(manager_api, client_co):
    stranger = Contact.objects.create(
        client=Client.objects.create(name="Other"), name="X", email="x@o.com"
    )
    res = manager_api.post(
        reverse("quotations:quotation-list"),
        {"client_id": client_co.pk, "title": "A", "contact_id": stranger.pk},
    )
    assert res.status_code == 400
    assert "contact_id" in res.data


def test_client_is_immutable_after_creation(manager_api, draft):
    other = Client.objects.create(name="Other")
    res = manager_api.patch(url(draft.pk), {"client_id": other.pk})
    assert res.status_code == 400
    assert "client_id" in res.data


# --- money pipeline ----------------------------------------------------------


def test_totals_discount_before_tax(manager_api, draft):
    """10 × 2000 = 20,000 → 10% line discount → 18,000 → 18% GST = 3,240."""
    item = draft.items.get()
    res = manager_api.patch(
        reverse("quotations:quotation-item-detail", args=[item.pk]),
        {"discount_percent": "10.00"},
    )
    assert res.status_code == 200
    assert res.data["line_subtotal"] == "20000.00"
    assert res.data["line_discount"] == "2000.00"
    assert res.data["taxable_amount"] == "18000.00"
    assert res.data["line_tax"] == "3240.00"
    assert res.data["line_total"] == "21240.00"
    draft.refresh_from_db()
    assert draft.grand_total == Decimal("21240.00")


def test_quote_level_discount_stacks_on_line_discount(manager_api, draft):
    item = draft.items.get()
    manager_api.patch(
        reverse("quotations:quotation-item-detail", args=[item.pk]),
        {"discount_percent": "10.00"},
    )
    res = manager_api.patch(url(draft.pk), {"discount_percent": "5.00"})
    assert res.status_code == 200
    # 20,000 → −10% = 18,000 → −5% = 17,100 → +18% GST = 20,178
    assert res.data["subtotal"] == "20000.00"
    assert res.data["discount_total"] == "2900.00"
    assert res.data["tax_total"] == "3078.00"
    assert res.data["grand_total"] == "20178.00"


def test_rounding_is_commercial_half_up(manager, draft):
    # 3 × 33.33 = 99.99 → 18% = 17.9982 → rounds to 18.00 (HALF_UP).
    services.add_item(
        quotation=draft,
        item=QuotationItem(
            description="Odd line", quantity=Decimal("3"), unit_price=Decimal("33.33")
        ),
        actor=manager,
    )
    line = draft.items.get(description="Odd line")
    assert line.line_tax == Decimal("18.00")
    assert line.line_total == Decimal("117.99")


def test_deleting_item_recomputes_totals(manager_api, draft):
    item = draft.items.get()
    res = manager_api.delete(reverse("quotations:quotation-item-detail", args=[item.pk]))
    assert res.status_code == 204
    draft.refresh_from_db()
    assert draft.grand_total == Decimal("0.00")


# --- draft-only editing ------------------------------------------------------


def test_items_frozen_after_submit(manager_api, manager, draft):
    services.submit_quotation(quotation=draft, actor=manager)
    res = manager_api.post(
        url(draft.pk, "items"),
        {"description": "Sneaky extra", "quantity": "1", "unit_price": "100"},
    )
    assert res.status_code == 400
    item = draft.items.get()
    res = manager_api.patch(
        reverse("quotations:quotation-item-detail", args=[item.pk]), {"unit_price": "9999"}
    )
    assert res.status_code == 400


def test_delete_allowed_only_for_drafts(manager_api, manager, draft):
    services.submit_quotation(quotation=draft, actor=manager)
    assert manager_api.delete(url(draft.pk)).status_code == 400
    services.request_changes(quotation=draft, actor=manager, note="back to draft")
    assert manager_api.delete(url(draft.pk)).status_code == 204


# --- workflow: submit → approve → send → decision ----------------------------


def test_submit_requires_items_and_validity(manager_api, manager, client_co):
    empty = services.create_quotation(
        quotation=Quotation(client=client_co, title="Empty"), actor=manager
    )
    assert manager_api.post(url(empty.pk, "submit")).status_code == 400  # no items
    services.add_item(
        quotation=empty,
        item=QuotationItem(description="X", quantity=Decimal("1"), unit_price=Decimal("1")),
        actor=manager,
    )
    assert manager_api.post(url(empty.pk, "submit")).status_code == 400  # no valid_until


def test_full_happy_path(manager, manager_api, other_manager_api, draft):
    assert manager_api.post(url(draft.pk, "submit")).status_code == 200
    res = other_manager_api.post(url(draft.pk, "approve"), {"note": "Numbers check out"})
    assert res.status_code == 200
    assert res.data["status"] == "approved"
    assert res.data["approved_by"]["name"]
    res = manager_api.post(url(draft.pk, "send"))
    assert res.status_code == 200 and res.data["sent_at"]
    res = manager_api.post(url(draft.pk, "accept"))
    assert res.status_code == 200
    assert res.data["status"] == "accepted" and res.data["accepted_at"]
    # Terminal: no further moves.
    assert manager_api.post(url(draft.pk, "decline")).status_code == 400


def test_cannot_approve_own_quotation(manager_api, manager, draft):
    services.submit_quotation(quotation=draft, actor=manager)
    res = manager_api.post(url(draft.pk, "approve"))
    assert res.status_code == 400
    assert "own quotation" in res.data["detail"]


def test_staff_cannot_approve(staff, staff_api, client_co):
    q = services.create_quotation(
        quotation=Quotation(client=client_co, title="Mine", valid_until=date(2099, 1, 1)),
        actor=staff,
    )
    services.add_item(
        quotation=q,
        item=QuotationItem(description="X", quantity=Decimal("1"), unit_price=Decimal("1")),
        actor=staff,
    )
    services.submit_quotation(quotation=q, actor=staff)
    assert staff_api.post(url(q.pk, "approve")).status_code == 403


def test_request_changes_requires_note_and_returns_to_draft(
    manager, manager_api, other_manager_api, draft
):
    services.submit_quotation(quotation=draft, actor=manager)
    assert other_manager_api.post(url(draft.pk, "request-changes"), {}).status_code == 400
    res = other_manager_api.post(url(draft.pk, "request-changes"), {"note": "Price too low"})
    assert res.status_code == 200
    assert res.data["status"] == "draft"
    assert res.data["approval_note"] == "Price too low"


def test_cannot_send_unapproved(manager_api, manager, draft):
    services.submit_quotation(quotation=draft, actor=manager)
    assert manager_api.post(url(draft.pk, "send")).status_code == 400  # skips approval


def test_declined_with_reason(manager, manager_api, other_manager_api, draft):
    services.submit_quotation(quotation=draft, actor=manager)
    other = User.objects.get(email="mgr2@x.com")
    services.approve_quotation(quotation=draft, actor=other)
    services.send_quotation(quotation=draft, actor=manager)
    res = manager_api.post(url(draft.pk, "decline"), {"reason": "Went with a competitor"})
    assert res.status_code == 200
    assert res.data["status"] == "declined"
    assert res.data["decline_reason"] == "Went with a competitor"


def test_status_not_writable_via_patch(manager_api, draft):
    res = manager_api.patch(url(draft.pk), {"status": "accepted"})
    assert res.status_code == 200  # unknown field silently ignored…
    draft.refresh_from_db()
    assert draft.status == Quotation.Status.DRAFT  # …status untouched


def test_transitions_recorded_on_timeline(manager, draft):
    services.submit_quotation(quotation=draft, actor=manager)
    events = Activity.objects.filter(object_id=draft.pk, verb=Activity.Verb.STATUS_CHANGED)
    assert events.count() == 1
    assert events.get().changes == {
        "field": "status",
        "from": "draft",
        "to": "pending_approval",
    }


def test_totals_include_item_added_through_nested_route(manager_api, draft):
    """
    Regression: the viewset prefetches items, and recompute_totals once read
    that stale cache — totals written after POST /items/ missed the new line.
    """
    res = manager_api.post(
        url(draft.pk, "items"),
        {"description": "Design", "quantity": "10", "unit_price": "2000"},
    )
    assert res.status_code == 201
    draft.refresh_from_db()
    # Two 10 × 2000 lines at 18% GST: 40,000 + 7,200.
    assert draft.subtotal == Decimal("40000.00")
    assert draft.grand_total == Decimal("47200.00")
