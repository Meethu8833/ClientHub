"""
Reply thread + first-response SLA clock, category and SLA-policy permission
boundaries, and the attachments-registry integration (notes on tickets).
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.tickets.models import SlaPolicy, Ticket, TicketCategory

PASSWORD = "Str0ng!pass123"

pytestmark = pytest.mark.django_db


def api_for(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def admin_api():
    return api_for(
        User.objects.create_user(email="admin@x.com", password=PASSWORD, role=User.Role.ADMIN)
    )


@pytest.fixture
def manager_api():
    return api_for(
        User.objects.create_user(email="mgr@x.com", password=PASSWORD, role=User.Role.MANAGER)
    )


@pytest.fixture
def staff():
    return User.objects.create_user(email="staff@x.com", password=PASSWORD, role=User.Role.STAFF)


@pytest.fixture
def staff_api(staff):
    return api_for(staff)


@pytest.fixture
def ticket(staff):
    return Ticket.objects.create(
        client=Client.objects.create(name="Acme"),
        category=TicketCategory.objects.create(name="Bug"),
        subject="Login broken",
        description="500 on login.",
        created_by=staff,
    )


def replies_url(ticket_id):
    return reverse("tickets:ticket-replies", args=[ticket_id])


# --- replies & the first-response clock -------------------------------------


def test_internal_note_does_not_stop_response_clock(staff_api, ticket):
    res = staff_api.post(
        replies_url(ticket.pk), {"body": "Looks like the deploy.", "is_internal": True}
    )
    assert res.status_code == 201
    ticket.refresh_from_db()
    assert ticket.first_response_at is None  # the client heard nothing yet


def test_first_public_reply_stops_response_clock(staff_api, staff, ticket):
    res = staff_api.post(replies_url(ticket.pk), {"body": "We are on it."})
    assert res.status_code == 201
    assert res.data["author"]["id"] == staff.id
    ticket.refresh_from_db()
    first = ticket.first_response_at
    assert first is not None
    # A second reply must NOT move the recorded first response.
    staff_api.post(replies_url(ticket.pk), {"body": "Update: fix deploying."})
    ticket.refresh_from_db()
    assert ticket.first_response_at == first


def test_thread_reads_oldest_first(staff_api, ticket):
    staff_api.post(replies_url(ticket.pk), {"body": "first"})
    staff_api.post(replies_url(ticket.pk), {"body": "second"})
    res = staff_api.get(replies_url(ticket.pk))
    assert [r["body"] for r in res.data["results"]] == ["first", "second"]


def test_no_replies_on_closed_ticket(manager_api, staff_api, ticket):
    manager_api.post(reverse("tickets:ticket-resolve", args=[ticket.pk]), {"summary": "done"})
    manager_api.post(reverse("tickets:ticket-close", args=[ticket.pk]))
    assert staff_api.post(replies_url(ticket.pk), {"body": "hello?"}).status_code == 400


# --- categories: manager/admin write, staff read ----------------------------


def test_category_permissions(staff_api, manager_api):
    cat_list = reverse("tickets:ticket-category-list")
    assert staff_api.post(cat_list, {"name": "Billing"}).status_code == 403
    res = manager_api.post(cat_list, {"name": "Billing"})
    assert res.status_code == 201
    assert staff_api.get(cat_list).status_code == 200
    # No hard delete — categories retire, they don't die.
    detail = reverse("tickets:ticket-category-detail", args=[res.data["id"]])
    assert manager_api.delete(detail).status_code == 405


# --- SLA policies: everyone reads, only admin tunes -------------------------


def test_sla_policy_permissions(staff_api, manager_api, admin_api):
    policy = SlaPolicy.objects.get(priority="urgent")  # seeded by migration
    detail = reverse("tickets:sla-policy-detail", args=[policy.pk])

    assert staff_api.get(detail).status_code == 200
    assert manager_api.patch(detail, {"first_response_minutes": 15}).status_code == 403
    res = admin_api.patch(detail, {"first_response_minutes": 15})
    assert res.status_code == 200
    assert res.data["first_response_minutes"] == 15


def test_sla_response_cannot_exceed_resolution(admin_api):
    policy = SlaPolicy.objects.get(priority="urgent")
    detail = reverse("tickets:sla-policy-detail", args=[policy.pk])
    res = admin_api.patch(detail, {"first_response_minutes": 10_000})
    assert res.status_code == 400


# --- attachments registry: notes pin to tickets -----------------------------


def test_notes_attach_to_tickets(staff_api, ticket):
    res = staff_api.post(
        reverse("activities:note-list"),
        {"body": "Client called again.", "content_type": "ticket", "object_id": ticket.pk},
    )
    assert res.status_code == 201
    assert res.data["target"] == {"content_type": "ticket", "object_id": ticket.pk}
