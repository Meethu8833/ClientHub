"""
Global search API tests: validation, match behaviour (substring, full-text
stemming, ranking), per-role scoping, and type filtering.

Data is seeded through the ORM (dashboard suite's reasoning: search READS
tables; the write paths are proven by the source modules' own suites).
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.billing.models import Invoice
from apps.clients.models import Client, Contact
from apps.projects.models import Project, ProjectMembership, Task
from apps.quotations.models import Quotation
from apps.tickets.models import Ticket, TicketCategory

PASSWORD = "Str0ng!pass123"

pytestmark = pytest.mark.django_db

URL = reverse("search:global")


# --- fixtures ---------------------------------------------------------------


@pytest.fixture
def admin():
    return User.objects.create_user(email="admin@x.com", password=PASSWORD, role=User.Role.ADMIN)


@pytest.fixture
def manager():
    return User.objects.create_user(email="mgr@x.com", password=PASSWORD, role=User.Role.MANAGER)


@pytest.fixture
def staff():
    return User.objects.create_user(
        email="staff@x.com", password=PASSWORD, role=User.Role.STAFF, first_name="Asha"
    )


def api_for(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def world(staff, manager):
    """Every entity type contains the word 'phoenix' somewhere findable."""
    acme = Client.objects.create(name="Acme Phoenix Ltd", city="Pune")
    dead = Client.objects.create(name="Phoenix Gone", is_active=False)
    Contact.objects.create(client=acme, name="Ravi Phoenixwala", position="CTO")

    # member project (staff belongs) vs foreign project (staff excluded)
    p_member = Project.objects.create(
        client=acme, name="Phoenix Portal", description="The relaunch."
    )
    ProjectMembership.objects.create(project=p_member, user=staff)
    p_foreign = Project.objects.create(
        client=acme, name="Secret Phoenix", description="Not for staff eyes."
    )

    Task.objects.create(project=p_member, title="Deploy phoenix build")
    Task.objects.create(project=p_foreign, title="Hidden phoenix task")

    cat = TicketCategory.objects.create(name="Bug")
    Ticket.objects.create(
        client=acme,
        category=cat,
        subject="Login broken",
        # FTS bait: query "deploying" must reach this via stemming.
        description="Regression after we deployed the phoenix release.",
    )

    Quotation.objects.create(
        quote_number="QT-2026-0001", client=acme, title="Phoenix support", created_by=staff
    )
    Quotation.objects.create(
        quote_number="QT-2026-0002", client=acme, title="Phoenix rollout", created_by=manager
    )

    Invoice.objects.create(client=acme, invoice_number="INV-2026-0042")

    return {
        "acme": acme,
        "dead": dead,
        "p_member": p_member,
        "p_foreign": p_foreign,
    }


def titles(body, type_):
    return [hit["title"] for hit in body["results"][type_]["items"]]


# --- validation -------------------------------------------------------------


def test_requires_auth():
    assert APIClient().get(URL, {"q": "phoenix"}).status_code == 401


def test_missing_or_short_q_is_400(manager):
    api = api_for(manager)
    assert api.get(URL).status_code == 400
    assert api.get(URL, {"q": " a "}).status_code == 400


def test_unknown_type_is_400(manager):
    res = api_for(manager).get(URL, {"q": "phoenix", "types": "cleints"})
    assert res.status_code == 400
    assert "cleints" in str(res.data)


def test_garbage_limit_is_400(manager):
    assert api_for(manager).get(URL, {"q": "phoenix", "limit": "lots"}).status_code == 400


# --- matching ---------------------------------------------------------------


def test_substring_match_is_case_insensitive(manager, world):
    body = api_for(manager).get(URL, {"q": "pHoEn", "types": "clients"}).json()
    assert titles(body, "clients") == ["Acme Phoenix Ltd"]


def test_soft_deleted_client_never_surfaces(manager, world):
    body = api_for(manager).get(URL, {"q": "Gone"}).json()
    assert titles(body, "clients") == []


def test_contact_found_with_client_subtitle(manager, world):
    body = api_for(manager).get(URL, {"q": "Ravi", "types": "contacts"}).json()
    (hit,) = body["results"]["contacts"]["items"]
    assert hit["subtitle"] == "CTO at Acme Phoenix Ltd"


def test_fts_stems_the_query(manager, world):
    # "deploying" is nowhere in the ticket verbatim; its stem "deploy"
    # matches "deployed" — this only passes through real full-text search.
    body = api_for(manager).get(URL, {"q": "deploying", "types": "tickets"}).json()
    assert titles(body, "tickets") == ["Login broken"]


def test_invoice_found_by_number_fragment(manager, world):
    body = api_for(manager).get(URL, {"q": "0042", "types": "invoices"}).json()
    assert titles(body, "invoices") == ["INV-2026-0042"]


def test_limit_and_has_more(manager, world):
    for i in range(3):
        Client.objects.create(name=f"Phoenix Clone {i}")
    body = api_for(manager).get(URL, {"q": "phoenix", "types": "clients", "limit": 2}).json()
    block = body["results"]["clients"]
    assert len(block["items"]) == 2
    assert block["has_more"] is True


# --- role scoping -----------------------------------------------------------


def test_staff_only_sees_member_projects_and_their_tasks(staff, world):
    body = api_for(staff).get(URL, {"q": "phoenix"}).json()
    assert titles(body, "projects") == ["Phoenix Portal"]
    assert titles(body, "tasks") == ["Deploy phoenix build"]


def test_manager_sees_all_projects(manager, world):
    body = api_for(manager).get(URL, {"q": "phoenix"}).json()
    assert sorted(titles(body, "projects")) == ["Phoenix Portal", "Secret Phoenix"]


def test_staff_quotations_scoped_to_own(staff, world):
    body = api_for(staff).get(URL, {"q": "phoenix"}).json()
    assert titles(body, "quotations") == ["Phoenix support"]


def test_invoices_absent_for_staff_even_when_requested(staff, world):
    body = api_for(staff).get(URL, {"q": "0042", "types": "invoices"}).json()
    # Not an error and not an empty list: the KEY is missing (billing
    # blackout — an empty block would leak that invoices exist to search).
    assert body["results"] == {}


def test_users_searchable_by_admin_only(admin, manager, staff, world):
    assert "users" not in api_for(manager).get(URL, {"q": "asha"}).json()["results"]
    body = api_for(admin).get(URL, {"q": "asha"}).json()
    assert titles(body, "users") == ["Asha"]


def test_types_filter_limits_response_keys(manager, world):
    body = api_for(manager).get(URL, {"q": "phoenix", "types": "clients,projects"}).json()
    assert sorted(body["results"]) == ["clients", "projects"]
