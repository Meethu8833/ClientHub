"""
Payment tests: the derived paid states (issued → partially_paid → paid and
back), the overpayment wall, balance arithmetic, deletion rollback, and the
activity trail on money moves.
"""

from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.activities.models import Activity
from apps.billing import services
from apps.billing.models import Invoice, InvoiceItem
from apps.clients.models import Client

PASSWORD = "Str0ng!pass123"

pytestmark = pytest.mark.django_db


@pytest.fixture
def manager():
    return User.objects.create_user(email="mgr@x.com", password=PASSWORD, role=User.Role.MANAGER)


@pytest.fixture
def manager_api(manager):
    c = APIClient()
    c.force_authenticate(user=manager)
    return c


@pytest.fixture
def issued(manager):
    """An issued invoice with grand_total 23600 (10 × 2000 + 18% tax)."""
    inv = services.create_invoice(
        invoice=Invoice(client=Client.objects.create(name="Acme")), actor=manager
    )
    services.add_item(
        invoice=inv,
        item=InvoiceItem(
            description="Backend", quantity=Decimal("10"), unit_price=Decimal("2000")
        ),
        actor=manager,
    )
    return services.issue_invoice(invoice=inv, actor=manager)


def pay_url(invoice):
    return reverse("billing:invoice-payments", args=[invoice.pk])


def pay(api, invoice, amount, **extra):
    body = {"amount": str(amount), "received_on": str(timezone.localdate()), **extra}
    return api.post(pay_url(invoice), body)


# --- recording ---------------------------------------------------------------


def test_partial_then_full_payment(manager_api, issued):
    resp = pay(manager_api, issued, "10000", method="upi", reference="UTR123")
    assert resp.status_code == 201

    detail = manager_api.get(reverse("billing:invoice-detail", args=[issued.pk])).data
    assert detail["status"] == "partially_paid"
    assert Decimal(detail["amount_paid"]) == Decimal("10000.00")
    assert Decimal(detail["balance_due"]) == Decimal("13600.00")
    assert detail["paid_at"] is None

    assert pay(manager_api, issued, "13600").status_code == 201
    detail = manager_api.get(reverse("billing:invoice-detail", args=[issued.pk])).data
    assert detail["status"] == "paid"
    assert Decimal(detail["balance_due"]) == Decimal("0.00")
    assert detail["paid_at"] is not None


def test_overpayment_is_rejected(manager_api, issued):
    assert pay(manager_api, issued, "23600.01").status_code == 400
    pay(manager_api, issued, "20000")
    # The wall also applies to the REMAINING balance, not just the total.
    assert pay(manager_api, issued, "5000").status_code == 400


def test_payment_needs_an_owing_invoice(manager_api, manager, issued):
    draft = services.create_invoice(
        invoice=Invoice(client=Client.objects.create(name="Globex")), actor=manager
    )
    assert pay(manager_api, draft, "100").status_code == 400  # never issued

    pay(manager_api, issued, "23600")
    assert pay(manager_api, issued, "1").status_code == 400  # already paid


def test_future_received_date_is_rejected(manager_api, issued):
    from datetime import timedelta

    tomorrow = timezone.localdate() + timedelta(days=1)
    resp = manager_api.post(
        pay_url(issued), {"amount": "100", "received_on": str(tomorrow)}
    )
    assert resp.status_code == 400


def test_void_is_blocked_once_money_arrived(manager_api, issued):
    pay(manager_api, issued, "100")
    resp = manager_api.post(
        reverse("billing:invoice-void", args=[issued.pk]), {"reason": "oops"}
    )
    assert resp.status_code == 400


# --- deletion rolls the state back -------------------------------------------


def test_delete_payment_rolls_status_back(manager_api, issued):
    pay(manager_api, issued, "10000")
    full = pay(manager_api, issued, "13600").data
    delete_resp = manager_api.delete(reverse("billing:payment-detail", args=[full["id"]]))
    assert delete_resp.status_code == 204

    issued.refresh_from_db()
    assert issued.status == Invoice.Status.PARTIALLY_PAID
    assert issued.paid_at is None
    assert issued.amount_paid == Decimal("10000.00")

    first = issued.payments.first()
    manager_api.delete(reverse("billing:payment-detail", args=[first.pk]))
    issued.refresh_from_db()
    assert issued.status == Invoice.Status.ISSUED
    assert issued.amount_paid == Decimal("0.00")


# --- the trail ---------------------------------------------------------------


def test_money_moves_land_on_the_activity_trail(manager_api, issued):
    payment = pay(manager_api, issued, "10000").data
    manager_api.delete(reverse("billing:payment-detail", args=[payment["id"]]))

    ct = ContentType.objects.get_for_model(Invoice)
    verbs = list(
        Activity.objects.filter(content_type=ct, object_id=issued.pk)
        .order_by("id")
        .values_list("verb", flat=True)
    )
    assert Activity.Verb.PAYMENT_RECORDED in verbs
    assert Activity.Verb.PAYMENT_DELETED in verbs
    recorded = Activity.objects.get(
        content_type=ct, object_id=issued.pk, verb=Activity.Verb.PAYMENT_RECORDED
    )
    assert recorded.changes["amount"] == "10000.00"
