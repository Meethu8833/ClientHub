"""
Payment-management tests (docs/payments-module.md): the pending → completed/
bounced lifecycle, refunds (per-payment cap, status rollback, delete-guard),
reconciliation locks, the global register + summary, and the trail.
"""

from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.activities.models import Activity
from apps.billing import services
from apps.billing.models import Invoice, InvoiceItem, Payment
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
def staff_api():
    staff = User.objects.create_user(email="dev@x.com", password=PASSWORD, role=User.Role.STAFF)
    c = APIClient()
    c.force_authenticate(user=staff)
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


def pay(api, invoice, amount, **extra):
    body = {"amount": str(amount), "received_on": str(timezone.localdate()), **extra}
    return api.post(reverse("billing:invoice-payments", args=[invoice.pk]), body)


def act(api, name, payment_id, body=None):
    return api.post(reverse(f"billing:payment-{name}", args=[payment_id]), body or {})


def refund(api, payment_id, amount, reason="cancelled scope", **extra):
    body = {
        "amount": str(amount),
        "refunded_on": str(timezone.localdate()),
        "reason": reason,
        **extra,
    }
    return api.post(reverse("billing:payment-refunds", args=[payment_id]), body)


# --- the pending lifecycle ----------------------------------------------------


def test_pending_payment_does_not_count_until_cleared(manager_api, issued):
    resp = pay(manager_api, issued, "10000", method="cheque", status="pending")
    assert resp.status_code == 201

    issued.refresh_from_db()
    assert issued.status == Invoice.Status.ISSUED  # a promise is not money
    assert issued.amount_paid == Decimal("0.00")

    assert act(manager_api, "clear", resp.data["id"]).status_code == 200
    issued.refresh_from_db()
    assert issued.status == Invoice.Status.PARTIALLY_PAID
    assert issued.amount_paid == Decimal("10000.00")


def test_bounced_payment_never_counts_and_is_terminal(manager_api, issued):
    p = pay(manager_api, issued, "23600", method="cheque", status="pending").data
    assert act(manager_api, "bounce", p["id"]).status_code == 200

    issued.refresh_from_db()
    assert issued.status == Invoice.Status.ISSUED
    assert issued.amount_paid == Decimal("0.00")
    # Terminal: a bounced instrument cannot be cleared afterwards.
    assert act(manager_api, "clear", p["id"]).status_code == 400
    # The row stays on record — the bounce is client history.
    assert issued.payments.filter(status=Payment.Status.BOUNCED).count() == 1


def test_completed_payment_cannot_transition(manager_api, issued):
    p = pay(manager_api, issued, "100").data  # default status: completed
    assert act(manager_api, "clear", p["id"]).status_code == 400
    assert act(manager_api, "bounce", p["id"]).status_code == 400


def test_cannot_record_a_payment_as_bounced(manager_api, issued):
    assert pay(manager_api, issued, "100", status="bounced").status_code == 400


def test_clear_rechecks_the_balance(manager_api, issued):
    """Two cheques may each fit the balance, but the second to clear must not."""
    a = pay(manager_api, issued, "20000", method="cheque", status="pending").data
    b = pay(manager_api, issued, "3600", method="cheque", status="pending").data
    # While both sat at the bank, a transfer paid most of the invoice.
    pay(manager_api, issued, "20000")

    assert act(manager_api, "clear", b["id"]).status_code == 200  # 3600 fits
    assert act(manager_api, "clear", a["id"]).status_code == 400  # 20000 no longer does


def test_void_allowed_when_only_bounced_payments_exist(manager_api, issued):
    p = pay(manager_api, issued, "500", method="cheque", status="pending").data
    act(manager_api, "bounce", p["id"])
    resp = manager_api.post(
        reverse("billing:invoice-void", args=[issued.pk]), {"reason": "wrong client"}
    )
    assert resp.status_code == 200  # no real money ever arrived


def test_deleting_a_pending_payment_moves_no_money(manager_api, issued):
    completed = pay(manager_api, issued, "1000").data
    pending = pay(manager_api, issued, "2000", method="cheque", status="pending").data
    assert (
        manager_api.delete(reverse("billing:payment-detail", args=[pending["id"]])).status_code
        == 204
    )
    issued.refresh_from_db()
    assert issued.amount_paid == Decimal("1000.00")
    assert completed  # the completed one is untouched


# --- refunds ------------------------------------------------------------------


def test_refund_reopens_a_paid_invoice(manager_api, issued):
    p = pay(manager_api, issued, "23600").data
    issued.refresh_from_db()
    assert issued.status == Invoice.Status.PAID

    resp = refund(manager_api, p["id"], "3600")
    assert resp.status_code == 201
    issued.refresh_from_db()
    assert issued.status == Invoice.Status.PARTIALLY_PAID
    assert issued.amount_paid == Decimal("23600.00")  # gross stays
    assert issued.amount_refunded == Decimal("3600.00")
    assert issued.balance_due == Decimal("3600.00")  # the client owes again
    assert issued.paid_at is None

    refund(manager_api, p["id"], "20000", reason="project cancelled")
    issued.refresh_from_db()
    assert issued.status == Invoice.Status.ISSUED  # fully unwound


def test_refund_capped_per_payment(manager_api, issued):
    first = pay(manager_api, issued, "10000").data
    pay(manager_api, issued, "13600")
    # 13600 is outstanding on the INVOICE, but this receipt only carried 10000.
    assert refund(manager_api, first["id"], "10000.01").status_code == 400
    assert refund(manager_api, first["id"], "6000").status_code == 201
    # The cap shrinks by what already went back.
    assert refund(manager_api, first["id"], "5000").status_code == 400
    assert refund(manager_api, first["id"], "4000").status_code == 201


def test_refund_requires_a_completed_payment_and_a_reason(manager_api, issued):
    pending = pay(manager_api, issued, "5000", method="cheque", status="pending").data
    assert refund(manager_api, pending["id"], "100").status_code == 400

    completed = pay(manager_api, issued, "5000").data
    resp = manager_api.post(
        reverse("billing:payment-refunds", args=[completed["id"]]),
        {"amount": "100", "refunded_on": str(timezone.localdate())},  # no reason
    )
    assert resp.status_code == 400


def test_refunded_payment_cannot_be_deleted_but_refund_can(manager_api, issued):
    p = pay(manager_api, issued, "5000").data
    r = refund(manager_api, p["id"], "1000").data
    assert (
        manager_api.delete(reverse("billing:payment-detail", args=[p["id"]])).status_code == 400
    )

    assert manager_api.delete(reverse("billing:refund-detail", args=[r["id"]])).status_code == 204
    issued.refresh_from_db()
    assert issued.amount_refunded == Decimal("0.00")
    # With its refunds gone, the payment is deletable again.
    assert (
        manager_api.delete(reverse("billing:payment-detail", args=[p["id"]])).status_code == 204
    )
    issued.refresh_from_db()
    assert issued.amount_paid == Decimal("0.00")


# --- reconciliation -----------------------------------------------------------


def test_reconcile_locks_the_payment(manager_api, issued):
    p = pay(manager_api, issued, "5000", reference="UTR777").data
    resp = act(manager_api, "reconcile", p["id"])
    assert resp.status_code == 200
    assert resp.data["is_reconciled"] is True
    assert resp.data["reconciled_by"]["id"]

    # Matched to the bank — deletion is refused until unreconciled.
    assert (
        manager_api.delete(reverse("billing:payment-detail", args=[p["id"]])).status_code == 400
    )
    assert act(manager_api, "reconcile", p["id"]).status_code == 400  # already matched

    assert act(manager_api, "unreconcile", p["id"]).status_code == 200
    assert (
        manager_api.delete(reverse("billing:payment-detail", args=[p["id"]])).status_code == 204
    )


def test_only_completed_payments_reconcile(manager_api, issued):
    p = pay(manager_api, issued, "5000", method="cheque", status="pending").data
    assert act(manager_api, "reconcile", p["id"]).status_code == 400


# --- the register and the summary ---------------------------------------------


def test_register_filters(manager_api, issued):
    pay(manager_api, issued, "1000", method="upi", reference="UTR1")
    p2 = pay(manager_api, issued, "2000", method="cheque", status="pending").data
    p3 = pay(manager_api, issued, "3000", method="bank_transfer").data
    act(manager_api, "reconcile", p3["id"])

    url = reverse("billing:payment-list")
    assert manager_api.get(url).data["count"] == 3
    assert manager_api.get(url, {"status": "pending"}).data["count"] == 1
    assert manager_api.get(url, {"method": "upi"}).data["count"] == 1
    assert manager_api.get(url, {"reconciled": "false"}).data["count"] == 2
    assert manager_api.get(url, {"reconciled": "true"}).data["count"] == 1
    assert manager_api.get(url, {"min_amount": "1500"}).data["count"] == 2
    row = manager_api.get(url, {"reference": "utr1"}).data["results"][0]
    assert row["invoice"]["number"].startswith("INV-")
    assert p2  # silence unused warning


def test_summary_reports_the_cash_position(manager_api, issued):
    p1 = pay(manager_api, issued, "10000", method="upi").data
    pay(manager_api, issued, "5000", method="cash")
    pending = pay(manager_api, issued, "2000", method="cheque", status="pending").data
    act(manager_api, "reconcile", p1["id"])
    refund(manager_api, p1["id"], "1500")

    data = manager_api.get(reverse("billing:payment-summary")).data
    assert data["received"] == {"total": "15000.00", "count": 2}
    assert data["by_method"]["upi"]["total"] == "10000.00"
    assert data["pending"] == {"total": "2000.00", "count": 1}
    assert data["unreconciled"] == {"total": "5000.00", "count": 1}
    assert data["refunded"] == {"total": "1500.00", "count": 1}

    # Out-of-range window: everything zeroes out.
    empty = manager_api.get(
        reverse("billing:payment-summary"), {"received_before": "2000-01-01"}
    ).data
    assert empty["received"]["count"] == 0
    assert manager_api.get(
        reverse("billing:payment-summary"), {"received_after": "not-a-date"}
    ).status_code == 400
    assert pending


# --- permissions and the trail ------------------------------------------------


def test_staff_has_no_access_to_payment_management(staff_api, manager_api, issued):
    p = pay(manager_api, issued, "1000").data
    assert staff_api.get(reverse("billing:payment-list")).status_code == 403
    assert staff_api.get(reverse("billing:payment-summary")).status_code == 403
    assert act(staff_api, "reconcile", p["id"]).status_code == 403
    assert refund(staff_api, p["id"], "100").status_code == 403


def test_money_moves_land_on_the_trail(manager_api, issued):
    p = pay(manager_api, issued, "5000", method="cheque", status="pending").data
    act(manager_api, "clear", p["id"])
    act(manager_api, "reconcile", p["id"])
    act(manager_api, "unreconcile", p["id"])
    r = refund(manager_api, p["id"], "500").data
    manager_api.delete(reverse("billing:refund-detail", args=[r["id"]]))

    from django.contrib.contenttypes.models import ContentType

    ct = ContentType.objects.get_for_model(Invoice)
    verbs = list(
        Activity.objects.filter(content_type=ct, object_id=issued.pk)
        .order_by("id")
        .values_list("verb", flat=True)
    )
    for verb in (
        Activity.Verb.PAYMENT_CLEARED,
        Activity.Verb.REFUND_RECORDED,
        Activity.Verb.REFUND_DELETED,
    ):
        assert verb in verbs
    assert verbs.count(Activity.Verb.RECONCILED) == 2  # match + unmatch both visible

    recorded = Activity.objects.get(
        content_type=ct, object_id=issued.pk, verb=Activity.Verb.REFUND_RECORDED
    )
    assert recorded.changes["reason"] == "cancelled scope"
