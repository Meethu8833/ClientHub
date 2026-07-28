"""
Dashboard API tests: KPI correctness, per-role scoping (incl. the billing
blackout for STAFF), chart shaping/zero-filling, and cache behaviour.

Data is seeded straight through the ORM (not the APIs): the dashboard reads
whatever is in the tables, and the source modules' own suites already prove
their write paths. Nullable audit fields (created_by, deadlines) are set only
when the aggregate under test reads them.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.billing.models import Invoice, Payment, Refund
from apps.clients.models import Client
from apps.projects.models import Project, ProjectMembership, Task
from apps.quotations.models import Quotation
from apps.tickets.models import Ticket, TicketCategory

PASSWORD = "Str0ng!pass123"

pytestmark = pytest.mark.django_db

SUMMARY_URL = reverse("dashboard:summary")
CHARTS_URL = reverse("dashboard:charts")


# --- fixtures ---------------------------------------------------------------


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
def manager_api(manager):
    return api_for(manager)


@pytest.fixture
def staff_api(staff):
    return api_for(staff)


@pytest.fixture
def world(staff, manager):
    """
    A small, hand-countable universe. Every assertion below traces back to
    a line here — if a number surprises you, read this fixture, not the SQL.
    """
    today = timezone.localdate()
    now = timezone.now()

    active = Client.objects.create(name="Acme", status=Client.Status.ACTIVE)
    prospect = Client.objects.create(name="Wayne", status=Client.Status.PROSPECT)

    # p1: staff is a member; running late (end_date yesterday, still open).
    p1 = Project.objects.create(
        client=active,
        name="Portal",
        status=Project.Status.IN_PROGRESS,
        end_date=today - timedelta(days=1),
    )
    ProjectMembership.objects.create(project=p1, user=staff)
    # p2: staff is NOT a member — invisible to them everywhere.
    p2 = Project.objects.create(client=active, name="Migration", status=Project.Status.PLANNED)

    # t1: staff's own, overdue. t2: someone else's, done, other project.
    Task.objects.create(
        project=p1, title="Fix login", assignee=staff, due_date=today - timedelta(days=1)
    )
    Task.objects.create(
        project=p2, title="Plan cutover", status=Task.Status.DONE, completed_at=now
    )

    cat = TicketCategory.objects.create(name="Bug")
    # tk1: open, unassigned, blown SLA. tk2: staff's, escalated, in progress.
    Ticket.objects.create(
        client=active,
        category=cat,
        subject="Site down",
        description="…",
        resolution_due_at=now - timedelta(hours=2),
    )
    Ticket.objects.create(
        client=active,
        category=cat,
        subject="Slow page",
        description="…",
        status=Ticket.Status.IN_PROGRESS,
        assignee=staff,
        is_escalated=True,
        escalated_at=now,
    )

    # q1: staff's draft. q2: manager's, with the client — pipeline money.
    Quotation.objects.create(
        quote_number="QT-2026-0001", client=active, title="Phase 2", created_by=staff
    )
    Quotation.objects.create(
        quote_number="QT-2026-0002",
        client=active,
        title="Support plan",
        created_by=manager,
        status=Quotation.Status.SENT,
        grand_total=Decimal("500.00"),
        submitted_at=now,
        sent_at=now,
    )

    # inv1: issued, part-paid, overdue → balance 800. inv2: a numberless draft.
    inv1 = Invoice.objects.create(
        client=active,
        invoice_number="INV-2026-0001",
        status=Invoice.Status.PARTIALLY_PAID,
        grand_total=Decimal("1000.00"),
        amount_paid=Decimal("200.00"),
        issue_date=today - timedelta(days=40),
        due_date=today - timedelta(days=10),
        issued_at=now - timedelta(days=40),
    )
    Invoice.objects.create(client=active, grand_total=Decimal("50.00"))
    Payment.objects.create(
        invoice=inv1, amount=Decimal("200.00"), received_on=today, recorded_by=manager
    )

    return {"clients": (active, prospect), "projects": (p1, p2), "invoice": inv1}


# --- summary: correctness & scoping ----------------------------------------


def test_summary_requires_auth(world):
    assert APIClient().get(SUMMARY_URL).status_code == 401


def test_summary_manager_counts(manager_api, world):
    data = manager_api.get(SUMMARY_URL).json()

    assert data["clients"] == {
        "total": 2, "prospect": 1, "active": 1, "inactive": 0, "new_this_month": 2,
    }
    assert data["projects"] == {
        "total": 2, "planned": 1, "in_progress": 1, "on_hold": 0, "completed": 0, "overdue": 1,
    }
    assert data["tickets"] == {
        "open": 2, "unassigned": 1, "escalated": 1, "sla_breached": 1, "my_open": 0,
    }
    assert data["quotations"]["awaiting_client"] == 1
    assert data["quotations"]["pipeline_value"] == "500.00"
    assert "as_of" in data


def test_summary_billing_block_manager_only(manager_api, staff_api, world):
    mgr = manager_api.get(SUMMARY_URL).json()
    assert mgr["billing"] == {
        "draft": 1,
        "awaiting_payment": 1,
        "outstanding_amount": "800.00",  # 1000 − 200 paid
        "overdue_count": 1,
        "overdue_amount": "800.00",
        "collected_this_month": "200.00",
    }
    assert "billing" not in staff_api.get(SUMMARY_URL).json()


def test_summary_staff_scoped(staff_api, world):
    data = staff_api.get(SUMMARY_URL).json()

    # Only the member project (p1) is visible/counted.
    assert data["projects"]["total"] == 1
    assert data["projects"]["overdue"] == 1
    # Tasks: p2's done task is out of scope AND closed either way.
    assert data["tasks"] == {
        "open": 1, "overdue": 1, "my_open": 1, "my_due_today": 0, "my_overdue": 1,
    }
    # Tickets are a shared queue — staff see the full numbers, plus their own.
    assert data["tickets"]["open"] == 2
    assert data["tickets"]["my_open"] == 1
    # Quotations: own rows only — the manager's SENT quote must not leak.
    assert data["quotations"]["draft"] == 1
    assert data["quotations"]["awaiting_client"] == 0
    assert data["quotations"]["pipeline_value"] == "0.00"


def test_refund_reopens_outstanding(manager_api, world):
    """A refund raises balance_due: outstanding must use gross − paid + refunded."""
    inv = world["invoice"]
    payment = inv.payments.first()
    Refund.objects.create(
        payment=payment, amount=Decimal("100.00"),
        refunded_on=timezone.localdate(), reason="goodwill",
    )
    inv.amount_refunded = Decimal("100.00")
    inv.save(update_fields=["amount_refunded"])

    data = manager_api.get(SUMMARY_URL).json()
    assert data["billing"]["outstanding_amount"] == "900.00"
    assert data["billing"]["collected_this_month"] == "100.00"  # 200 in − 100 back


# --- charts -----------------------------------------------------------------


def test_charts_manager_revenue_zero_filled(manager_api, world):
    data = manager_api.get(CHARTS_URL).json()
    series = data["revenue_by_month"]

    assert len(series) == 12
    this_month = timezone.localdate().strftime("%Y-%m")
    assert series[-1] == {"month": this_month, "revenue": "200.00"}
    # Months with no payments exist with an explicit zero, not a gap.
    assert all(p["revenue"] == "0.00" for p in series[:-1])

    assert data["invoice_aging"]["days_1_30"] == "800.00"
    assert data["invoice_aging"]["current"] == "0.00"


def test_charts_tickets_and_project_status(manager_api, world):
    data = manager_api.get(CHARTS_URL).json()

    months = data["tickets_by_month"]
    assert len(months) == 6
    assert months[-1]["opened"] == 2
    assert months[-1]["resolved"] == 0

    statuses = {row["status"]: row["count"] for row in data["project_status"]}
    assert statuses == {"in_progress": 1, "planned": 1}


def test_charts_staff_no_money_series(staff_api, world):
    data = staff_api.get(CHARTS_URL).json()
    assert "revenue_by_month" not in data
    assert "invoice_aging" not in data
    # …and the status donut is scoped to member projects.
    assert data["project_status"] == [{"status": "in_progress", "label": "In progress", "count": 1}]


# --- caching ----------------------------------------------------------------


def test_summary_is_cached_within_ttl(manager_api, world):
    first = manager_api.get(SUMMARY_URL).json()
    assert first["clients"]["total"] == 2

    Client.objects.create(name="Stark", status=Client.Status.ACTIVE)

    # Within the TTL the cached payload is served — deliberately stale.
    assert manager_api.get(SUMMARY_URL).json()["clients"]["total"] == 2
    # Once the entry is gone (here: cleared; in prod: TTL expiry) it's fresh.
    cache.clear()
    assert manager_api.get(SUMMARY_URL).json()["clients"]["total"] == 3


def test_cache_isolated_per_staff_user(staff_api, staff2, world):
    """staff2 must not be served staff's cached numbers."""
    assert staff_api.get(SUMMARY_URL).json()["projects"]["total"] == 1
    data2 = api_for(staff2).get(SUMMARY_URL).json()
    assert data2["projects"]["total"] == 0  # member of nothing
    assert data2["tasks"]["my_open"] == 0


def test_manager_and_admin_share_global_scope(manager_api, world):
    """Admin gets the same global payload (and may reuse the manager's cache)."""
    admin = User.objects.create_user(
        email="admin@x.com", password=PASSWORD, role=User.Role.ADMIN
    )
    mgr = manager_api.get(SUMMARY_URL).json()
    adm = api_for(admin).get(SUMMARY_URL).json()
    assert adm == mgr
