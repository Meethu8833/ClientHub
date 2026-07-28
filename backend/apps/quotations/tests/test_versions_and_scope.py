"""
Versioning (revise), the expiry sweep + accept guard, staff visibility
scoping, and the attachments-registry integration (notes on quotations).
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
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
def staff():
    return User.objects.create_user(email="staff@x.com", password=PASSWORD, role=User.Role.STAFF)


@pytest.fixture
def staff_api(staff):
    return api_for(staff)


@pytest.fixture
def client_co():
    return Client.objects.create(name="Acme")


def make_sent_quote(owner, client_co, valid_until=None):
    """Create → item → submit → approve (by a second manager) → send."""
    approver, _ = User.objects.get_or_create(
        email="approver@x.com", defaults={"role": User.Role.MANAGER}
    )
    q = services.create_quotation(
        quotation=Quotation(
            client=client_co,
            title="Offer",
            valid_until=valid_until or timezone.localdate() + timedelta(days=30),
        ),
        actor=owner,
    )
    services.add_item(
        quotation=q,
        item=QuotationItem(description="Work", quantity=Decimal("2"), unit_price=Decimal("500")),
        actor=owner,
    )
    services.submit_quotation(quotation=q, actor=owner)
    services.approve_quotation(quotation=q, actor=approver)
    services.send_quotation(quotation=q, actor=owner)
    return q


def url(pk, verb=None):
    if verb:
        return reverse(f"quotations:quotation-{verb}", args=[pk])
    return reverse("quotations:quotation-detail", args=[pk])


# --- versioning --------------------------------------------------------------


def test_revise_clones_items_and_supersedes_sent_version(manager_api, manager, client_co):
    v1 = make_sent_quote(manager, client_co)
    res = manager_api.post(url(v1.pk, "revise"))
    assert res.status_code == 201
    assert res.data["version"] == 2
    assert res.data["quote_number"] == v1.quote_number
    assert res.data["display_number"] == f"{v1.quote_number} v2"
    assert res.data["status"] == "draft"
    assert res.data["revision_of_id"] == v1.pk
    assert res.data["valid_until"] is None  # fresh window must be chosen
    assert len(res.data["items"]) == 1  # lines cloned
    assert res.data["grand_total"] == "1180.00"  # 1000 + 18% GST
    v1.refresh_from_db()
    assert v1.status == Quotation.Status.SUPERSEDED


def test_revise_keeps_declined_status_on_old_version(manager_api, manager, client_co):
    v1 = make_sent_quote(manager, client_co)
    services.decline_quotation(quotation=v1, actor=manager, reason="too costly")
    res = manager_api.post(url(v1.pk, "revise"))
    assert res.status_code == 201
    v1.refresh_from_db()
    assert v1.status == Quotation.Status.DECLINED  # history unchanged


def test_cannot_revise_twice_or_from_accepted(manager_api, manager, client_co):
    v1 = make_sent_quote(manager, client_co)
    assert manager_api.post(url(v1.pk, "revise")).status_code == 201
    assert manager_api.post(url(v1.pk, "revise")).status_code == 400  # already revised

    v_accepted = make_sent_quote(manager, Client.objects.create(name="Beta"))
    services.accept_quotation(quotation=v_accepted, actor=manager)
    assert manager_api.post(url(v_accepted.pk, "revise")).status_code == 400


def test_draft_cannot_be_revised(manager_api, manager, client_co):
    q = services.create_quotation(
        quotation=Quotation(client=client_co, title="Draft"), actor=manager
    )
    assert manager_api.post(url(q.pk, "revise")).status_code == 400


# --- validity & expiry -------------------------------------------------------


def test_expiry_sweep_marks_lapsed_sent_quotes(manager, client_co):
    q = make_sent_quote(manager, client_co)
    # Backdate the window after sending (can't submit with a past date).
    Quotation.objects.filter(pk=q.pk).update(valid_until=timezone.localdate() - timedelta(days=1))
    call_command("expire_quotations")
    q.refresh_from_db()
    assert q.status == Quotation.Status.EXPIRED


def test_cannot_accept_lapsed_quote_before_sweep_runs(manager_api, manager, client_co):
    q = make_sent_quote(manager, client_co)
    Quotation.objects.filter(pk=q.pk).update(valid_until=timezone.localdate() - timedelta(days=1))
    res = manager_api.post(url(q.pk, "accept"))
    assert res.status_code == 400
    assert "expired" in res.data["detail"]


def test_expired_quote_can_be_revised(manager_api, manager, client_co):
    q = make_sent_quote(manager, client_co)
    Quotation.objects.filter(pk=q.pk).update(valid_until=timezone.localdate() - timedelta(days=1))
    call_command("expire_quotations")
    assert manager_api.post(url(q.pk, "revise")).status_code == 201


def test_expired_filter(manager_api, manager, client_co):
    q = make_sent_quote(manager, client_co)
    Quotation.objects.filter(pk=q.pk).update(valid_until=timezone.localdate() - timedelta(days=1))
    make_sent_quote(manager, Client.objects.create(name="Beta"))
    res = manager_api.get(reverse("quotations:quotation-list"), {"expired": "true"})
    assert res.status_code == 200
    assert [row["id"] for row in res.data["results"]] == [q.pk]
    assert res.data["results"][0]["is_expired"] is True


# --- visibility & permission scope ------------------------------------------


def test_staff_see_only_own_quotations(staff_api, staff, manager, client_co):
    mine = services.create_quotation(
        quotation=Quotation(client=client_co, title="Mine"), actor=staff
    )
    services.create_quotation(
        quotation=Quotation(client=client_co, title="Not mine"), actor=manager
    )
    res = staff_api.get(reverse("quotations:quotation-list"))
    assert [row["id"] for row in res.data["results"]] == [mine.pk]
    # Out-of-scope detail 404s — existence is not leaked.
    other = Quotation.objects.get(title="Not mine")
    assert staff_api.get(url(other.pk)).status_code == 404


def test_manager_sees_all(manager_api, staff, manager, client_co):
    services.create_quotation(
        quotation=Quotation(client=client_co, title="Staff quote"), actor=staff
    )
    res = manager_api.get(reverse("quotations:quotation-list"))
    assert res.data["count"] == 1


def test_staff_cannot_edit_others_items(staff_api, manager, client_co):
    q = services.create_quotation(
        quotation=Quotation(client=client_co, title="Managers"), actor=manager
    )
    item = services.add_item(
        quotation=q,
        item=QuotationItem(description="X", quantity=Decimal("1"), unit_price=Decimal("1")),
        actor=manager,
    )
    res = staff_api.patch(
        reverse("quotations:quotation-item-detail", args=[item.pk]), {"unit_price": "0"}
    )
    assert res.status_code == 404  # scoped out, not just forbidden


# --- attachments integration -------------------------------------------------


def test_note_attaches_to_quotation(manager_api, manager, client_co):
    q = services.create_quotation(
        quotation=Quotation(client=client_co, title="Notable"), actor=manager
    )
    res = manager_api.post(
        reverse("activities:note-list"),
        {"content_type": "quotation", "object_id": q.pk, "body": "Client wants a call first."},
    )
    assert res.status_code == 201
    ct = ContentType.objects.get_for_model(Quotation)
    listing = manager_api.get(
        reverse("activities:note-list"), {"content_type": "quotation", "object_id": q.pk}
    )
    assert listing.status_code == 200
    assert listing.data["count"] == 1
    assert ct.model == "quotation"
