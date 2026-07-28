"""
Ticket API tests: creation + SLA stamping, the lifecycle state machine,
per-role permission boundaries, escalation, and the overdue filter.
"""

from datetime import timedelta

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.activities.models import Activity
from apps.clients.models import Client, Contact
from apps.tickets.models import Ticket, TicketCategory

PASSWORD = "Str0ng!pass123"

pytestmark = pytest.mark.django_db

LIST_URL = reverse("tickets:ticket-list")


def url(ticket_id, action=None):
    if action:
        return reverse(f"tickets:ticket-{action}", args=[ticket_id])
    return reverse("tickets:ticket-detail", args=[ticket_id])


# --- fixtures ---------------------------------------------------------------


@pytest.fixture
def admin():
    return User.objects.create_user(email="admin@x.com", password=PASSWORD, role=User.Role.ADMIN)


@pytest.fixture
def manager():
    return User.objects.create_user(email="mgr@x.com", password=PASSWORD, role=User.Role.MANAGER)


@pytest.fixture
def staff():
    return User.objects.create_user(email="staff@x.com", password=PASSWORD, role=User.Role.STAFF)


@pytest.fixture
def staff2():
    return User.objects.create_user(email="staff2@x.com", password=PASSWORD, role=User.Role.STAFF)


def api_for(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def admin_api(admin):
    return api_for(admin)


@pytest.fixture
def manager_api(manager):
    return api_for(manager)


@pytest.fixture
def staff_api(staff):
    return api_for(staff)


@pytest.fixture
def acme():
    return Client.objects.create(name="Acme Fintech")


@pytest.fixture
def contact(acme):
    return Contact.objects.create(client=acme, name="Priya CTO")


@pytest.fixture
def category():
    return TicketCategory.objects.create(name="Bug")


@pytest.fixture
def ticket(acme, category, staff):
    """A plain OPEN ticket created through the API by staff."""
    res = api_for(staff).post(
        LIST_URL,
        {
            "client_id": acme.id,
            "category_id": category.id,
            "subject": "Login broken",
            "description": "Users get a 500 on login since this morning.",
        },
    )
    assert res.status_code == 201, res.data
    return Ticket.objects.get(pk=res.data["id"])


# --- creation & SLA stamping ------------------------------------------------


def test_create_stamps_sla_from_policy(ticket):
    # Default MEDIUM policy (seed migration): respond in 4h, resolve in 24h.
    assert ticket.status == Ticket.Status.OPEN
    assert ticket.first_response_due_at == ticket.created_at + timedelta(hours=4)
    assert ticket.resolution_due_at == ticket.created_at + timedelta(hours=24)


def test_create_records_activity(ticket):
    ct = ContentType.objects.get_for_model(Ticket)
    verbs = Activity.objects.filter(content_type=ct, object_id=ticket.pk).values_list(
        "verb", flat=True
    )
    assert Activity.Verb.CREATED in verbs


def test_contact_must_belong_to_client(staff_api, acme, category):
    stranger = Contact.objects.create(
        client=Client.objects.create(name="Other Co"), name="Wrong Person"
    )
    res = staff_api.post(
        LIST_URL,
        {
            "client_id": acme.id,
            "category_id": category.id,
            "contact_id": stranger.id,
            "subject": "x",
            "description": "y",
        },
    )
    assert res.status_code == 400
    assert "contact_id" in res.data


def test_retired_category_rejected_for_new_tickets(staff_api, acme):
    retired = TicketCategory.objects.create(name="Old", is_active=False)
    res = staff_api.post(
        LIST_URL,
        {"client_id": acme.id, "category_id": retired.id, "subject": "x", "description": "y"},
    )
    assert res.status_code == 400


def test_priority_change_restamps_sla(manager_api, ticket):
    res = manager_api.patch(url(ticket.pk), {"priority": "urgent"})
    assert res.status_code == 200
    ticket.refresh_from_db()
    # URGENT policy: 30 min response / 4 h resolution.
    assert ticket.first_response_due_at == ticket.created_at + timedelta(minutes=30)
    assert ticket.resolution_due_at == ticket.created_at + timedelta(hours=4)


def test_ticket_cannot_move_to_another_client(manager_api, ticket):
    other = Client.objects.create(name="Other Co")
    res = manager_api.patch(url(ticket.pk), {"client_id": other.id})
    assert res.status_code == 400


def test_no_delete_endpoint(admin_api, ticket):
    assert admin_api.delete(url(ticket.pk)).status_code == 405


# --- lifecycle --------------------------------------------------------------


def test_claim_assigns_and_starts(staff_api, staff, ticket):
    res = staff_api.post(url(ticket.pk, "claim"))
    assert res.status_code == 200
    assert res.data["assignee"]["id"] == staff.id
    assert res.data["status"] == "in_progress"


def test_claim_someone_elses_ticket_rejected(staff_api, staff2, ticket):
    ticket.assignee = staff2
    ticket.save()
    assert staff_api.post(url(ticket.pk, "claim")).status_code == 400


def test_staff_cannot_assign_manager_can(staff_api, manager_api, staff2, ticket):
    assert staff_api.post(url(ticket.pk, "assign"), {"assignee_id": staff2.id}).status_code == 403
    res = manager_api.post(url(ticket.pk, "assign"), {"assignee_id": staff2.id})
    assert res.status_code == 200
    assert res.data["assignee"]["id"] == staff2.id


def test_unassign_returns_ticket_to_queue(manager_api, staff2, ticket):
    manager_api.post(url(ticket.pk, "assign"), {"assignee_id": staff2.id})
    # format="json": None isn't expressible in the default multipart encoding
    res = manager_api.post(url(ticket.pk, "assign"), {"assignee_id": None}, format="json")
    assert res.status_code == 200
    assert res.data["status"] == "open"
    assert res.data["assignee"] is None


def test_resolve_requires_summary(staff_api, staff, ticket):
    staff_api.post(url(ticket.pk, "claim"))
    assert staff_api.post(url(ticket.pk, "resolve"), {}).status_code == 400
    res = staff_api.post(url(ticket.pk, "resolve"), {"summary": "Rolled back bad deploy."})
    assert res.status_code == 200
    assert res.data["status"] == "resolved"
    assert res.data["resolved_at"] is not None
    assert res.data["resolution_summary"] == "Rolled back bad deploy."


def test_staff_cannot_resolve_unassigned_or_foreign_ticket(staff_api, staff2, ticket):
    # Unassigned: staff must claim first.
    assert staff_api.post(url(ticket.pk, "resolve"), {"summary": "s"}).status_code == 403
    ticket.assignee = staff2
    ticket.save()
    assert staff_api.post(url(ticket.pk, "resolve"), {"summary": "s"}).status_code == 403


def test_close_and_reopen_cycle(manager_api, ticket):
    manager_api.post(url(ticket.pk, "resolve"), {"summary": "Fixed."})
    res = manager_api.post(url(ticket.pk, "close"))
    assert res.status_code == 200
    assert res.data["status"] == "closed"

    res = manager_api.post(url(ticket.pk, "reopen"))
    assert res.status_code == 200
    assert res.data["status"] == "in_progress"
    assert res.data["resolved_at"] is None
    assert res.data["reopened_count"] == 1


def test_reopen_of_live_ticket_rejected(manager_api, ticket):
    assert manager_api.post(url(ticket.pk, "reopen")).status_code == 400


def test_resolve_closed_ticket_rejected(manager_api, ticket):
    manager_api.post(url(ticket.pk, "resolve"), {"summary": "s"})
    manager_api.post(url(ticket.pk, "close"))
    assert manager_api.post(url(ticket.pk, "resolve"), {"summary": "again"}).status_code == 400


def test_status_not_writable_via_patch(manager_api, ticket):
    manager_api.patch(url(ticket.pk), {"status": "closed"})
    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.OPEN  # silently ignored: not a write field


# --- escalation -------------------------------------------------------------


def test_escalate_sets_flag_and_history(staff_api, staff, ticket):
    res = staff_api.post(url(ticket.pk, "escalate"), {"reason": "Client threatening churn."})
    assert res.status_code == 200
    assert res.data["is_escalated"] is True
    assert res.data["escalated_by"]["id"] == staff.id
    ct = ContentType.objects.get_for_model(Ticket)
    assert Activity.objects.filter(
        content_type=ct, object_id=ticket.pk, verb=Activity.Verb.ESCALATED
    ).exists()
    # Escalating twice is a caller bug.
    assert staff_api.post(url(ticket.pk, "escalate"), {}).status_code == 400


def test_overdue_filter_and_auto_escalation(manager_api, ticket):
    assert manager_api.get(LIST_URL, {"overdue": "true"}).data["count"] == 0
    # Time-travel: push both deadlines into the past.
    Ticket.objects.filter(pk=ticket.pk).update(
        first_response_due_at=timezone.now() - timedelta(hours=2),
        resolution_due_at=timezone.now() - timedelta(hours=1),
    )
    assert manager_api.get(LIST_URL, {"overdue": "true"}).data["count"] == 1

    call_command("escalate_overdue_tickets")
    ticket.refresh_from_db()
    assert ticket.is_escalated is True
    assert ticket.escalated_by is None  # the system, not a person
    assert "SLA breached" in ticket.escalation_reason
