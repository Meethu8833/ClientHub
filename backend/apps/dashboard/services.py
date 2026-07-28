"""
Dashboard aggregation service (docs/dashboard-module.md).

Every function here answers one question with ONE SQL query (or two where two
tables are involved) using conditional aggregation:

    Count("id", filter=Q(...))   →   COUNT(*) FILTER (WHERE ...)

so a whole KPI block — total / by-status / overdue — is a single table scan,
not one query per number. The DB does the math; Python only shapes the dict.

Role scoping mirrors the source modules exactly (§8): whatever a role can
LIST it may also COUNT — the dashboard must never leak a number a user could
not reach by paging the underlying endpoint.

    clients      shared (every role reads all clients)
    projects     STAFF → member projects only
    tasks        STAFF → tasks of member projects only
    tickets      shared queue (every role sees every ticket)
    quotations   STAFF → own (created_by) only
    billing      manager/admin ONLY — the block is absent for STAFF

Money leaves this module as str (same idiom as /payments/summary/): JSON has
no Decimal, floats corrupt money, so "1234.50" it is. Counts stay int.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, F, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from apps.accounts.models import User
from apps.billing.models import Invoice, Payment, Refund
from apps.clients.models import Client
from apps.projects.models import Project, Task
from apps.quotations.models import Quotation
from apps.tickets.models import Ticket

# Sum(F() - F() + F()) mixes columns, so the output type must be spelled out.
MONEY = DecimalField(max_digits=14, decimal_places=2)

# Balance still owed on an invoice, as SQL. amount_paid is GROSS (refunds
# tracked separately), hence the "+ amount_refunded" — a refund reopens the
# balance. Mirrors Invoice.net_paid/balance_due, but those are Python
# properties: fine for one instance, useless for aggregating 10 000 rows.
BALANCE_DUE = F("grand_total") - F("amount_paid") + F("amount_refunded")

# Only these statuses owe money. DRAFT owes nothing yet, PAID nothing any
# more, VOID never again.
OWING = Q(status__in=[Invoice.Status.ISSUED, Invoice.Status.PARTIALLY_PAID])


def _money(value) -> str:
    """Decimal|None → '1234.50'. None is what Sum() returns over zero rows."""
    return str((value if value is not None else Decimal("0")).quantize(Decimal("0.01")))


def _month_start() -> date:
    return timezone.localdate().replace(day=1)


def _month_starts(n: int) -> list[date]:
    """The first day of the last `n` months, oldest first, current month last."""
    y, m = timezone.localdate().year, timezone.localdate().month
    out = []
    for _ in range(n):
        out.append(date(y, m, 1))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return list(reversed(out))


# ---------------------------------------------------------------------------
# Scoped querysets — the single place the dashboard's visibility rules live.
# ---------------------------------------------------------------------------


def _visible_projects(user):
    qs = Project.objects.all()
    if user.role == User.Role.STAFF:
        # Safe from join-duplication: (project, user) is unique, so this
        # join matches at most one membership row per project.
        qs = qs.filter(memberships__user=user)
    return qs


def _visible_tasks(user):
    qs = Task.objects.all()
    if user.role == User.Role.STAFF:
        qs = qs.filter(project__memberships__user=user)
    return qs


def _visible_quotations(user):
    qs = Quotation.objects.all()
    if user.role == User.Role.STAFF:
        qs = qs.filter(created_by=user)
    return qs


# ---------------------------------------------------------------------------
# Summary blocks — one aggregate query each.
# ---------------------------------------------------------------------------


def _clients_block() -> dict:
    return Client.objects.filter(is_active=True).aggregate(
        total=Count("id"),
        prospect=Count("id", filter=Q(status=Client.Status.PROSPECT)),
        active=Count("id", filter=Q(status=Client.Status.ACTIVE)),
        inactive=Count("id", filter=Q(status=Client.Status.INACTIVE)),
        new_this_month=Count("id", filter=Q(created_at__date__gte=_month_start())),
    )


def _projects_block(user) -> dict:
    today = timezone.localdate()
    # A project can only be "late" while there is still work to be late on.
    running = Q(
        status__in=[
            Project.Status.PLANNED,
            Project.Status.IN_PROGRESS,
            Project.Status.ON_HOLD,
        ]
    )
    return _visible_projects(user).aggregate(
        total=Count("id"),
        planned=Count("id", filter=Q(status=Project.Status.PLANNED)),
        in_progress=Count("id", filter=Q(status=Project.Status.IN_PROGRESS)),
        on_hold=Count("id", filter=Q(status=Project.Status.ON_HOLD)),
        completed=Count("id", filter=Q(status=Project.Status.COMPLETED)),
        overdue=Count("id", filter=running & Q(end_date__lt=today)),
    )


def _tasks_block(user) -> dict:
    today = timezone.localdate()
    open_ = ~Q(status=Task.Status.DONE)
    mine = Q(assignee=user)
    return _visible_tasks(user).aggregate(
        open=Count("id", filter=open_),
        overdue=Count("id", filter=open_ & Q(due_date__lt=today)),
        my_open=Count("id", filter=open_ & mine),
        my_due_today=Count("id", filter=open_ & mine & Q(due_date=today)),
        my_overdue=Count("id", filter=open_ & mine & Q(due_date__lt=today)),
    )


def _tickets_block(user) -> dict:
    now = timezone.now()
    open_ = Q(status__in=Ticket.OPEN_STATUSES)
    return Ticket.objects.aggregate(
        open=Count("id", filter=open_),
        unassigned=Count("id", filter=open_ & Q(assignee__isnull=True)),
        escalated=Count("id", filter=open_ & Q(is_escalated=True)),
        # Work still open past its promised resolution time. NULL deadlines
        # (no SLA stamped) are excluded by `<` semantics — correct: no
        # promise, no breach.
        sla_breached=Count("id", filter=open_ & Q(resolution_due_at__lt=now)),
        my_open=Count("id", filter=open_ & Q(assignee=user)),
    )


def _quotations_block(user) -> dict:
    data = _visible_quotations(user).aggregate(
        draft=Count("id", filter=Q(status=Quotation.Status.DRAFT)),
        awaiting_approval=Count("id", filter=Q(status=Quotation.Status.PENDING_APPROVAL)),
        awaiting_client=Count("id", filter=Q(status=Quotation.Status.SENT)),
        accepted_this_month=Count(
            "id",
            filter=Q(
                status=Quotation.Status.ACCEPTED,
                accepted_at__date__gte=_month_start(),
            ),
        ),
        # Money that COULD land: everything submitted but not yet decided.
        pipeline_value=Sum(
            "grand_total",
            filter=Q(
                status__in=[
                    Quotation.Status.PENDING_APPROVAL,
                    Quotation.Status.APPROVED,
                    Quotation.Status.SENT,
                ]
            ),
        ),
    )
    data["pipeline_value"] = _money(data["pipeline_value"])
    return data


def _billing_block() -> dict:
    """Manager/admin only — STAFF have zero billing access (§8)."""
    today = timezone.localdate()
    overdue = OWING & Q(due_date__lt=today)
    inv = Invoice.objects.aggregate(
        draft=Count("id", filter=Q(status=Invoice.Status.DRAFT)),
        awaiting_payment=Count("id", filter=OWING),
        outstanding_amount=Sum(BALANCE_DUE, filter=OWING, output_field=MONEY),
        overdue_count=Count("id", filter=overdue),
        overdue_amount=Sum(BALANCE_DUE, filter=overdue, output_field=MONEY),
    )
    # Cash actually in this month, net of what went back out. Two more small
    # queries — payments and refunds are different tables, and a UNION would
    # buy nothing but obscurity.
    collected = Payment.objects.filter(
        status=Payment.Status.COMPLETED, received_on__gte=_month_start()
    ).aggregate(t=Sum("amount"))["t"] or Decimal("0")
    refunded = Refund.objects.filter(refunded_on__gte=_month_start()).aggregate(
        t=Sum("amount")
    )["t"] or Decimal("0")
    return {
        "draft": inv["draft"],
        "awaiting_payment": inv["awaiting_payment"],
        "outstanding_amount": _money(inv["outstanding_amount"]),
        "overdue_count": inv["overdue_count"],
        "overdue_amount": _money(inv["overdue_amount"]),
        "collected_this_month": _money(collected - refunded),
    }


def get_summary(user) -> dict:
    """
    Everything the home screen's KPI tiles need, in one payload.

    `as_of` is stamped here (not in the view) so a cache hit truthfully shows
    WHEN the numbers were computed, not when they were served.
    """
    data = {
        "clients": _clients_block(),
        "projects": _projects_block(user),
        "tasks": _tasks_block(user),
        "tickets": _tickets_block(user),
        "quotations": _quotations_block(user),
        "as_of": timezone.now().isoformat(),
    }
    if user.role != User.Role.STAFF:
        data["billing"] = _billing_block()
    return data


# ---------------------------------------------------------------------------
# Charts — time series and distributions, shaped ready for the frontend.
# ---------------------------------------------------------------------------


def _project_status_chart(user) -> list[dict]:
    rows = (
        _visible_projects(user)
        .values("status")  # + annotate = GROUP BY status
        .annotate(count=Count("id"))
        .order_by("status")
    )
    return [
        {"status": r["status"], "label": Project.Status(r["status"]).label, "count": r["count"]}
        for r in rows
    ]


def _revenue_by_month(months: int = 12) -> list[dict]:
    """
    Net cash per month: completed payments minus refunds, grouped by month
    IN SQL (TruncMonth → GROUP BY), zero-filled in Python — GROUP BY only
    returns months that have rows, but a chart needs an unbroken axis.
    """
    starts = _month_starts(months)
    paid = (
        Payment.objects.filter(status=Payment.Status.COMPLETED, received_on__gte=starts[0])
        .annotate(month=TruncMonth("received_on"))
        .values("month")
        .annotate(total=Sum("amount"))
    )
    refunds = (
        Refund.objects.filter(refunded_on__gte=starts[0])
        .annotate(month=TruncMonth("refunded_on"))
        .values("month")
        .annotate(total=Sum("amount"))
    )
    paid_by = {r["month"]: r["total"] for r in paid}
    ref_by = {r["month"]: r["total"] for r in refunds}
    zero = Decimal("0")
    return [
        {
            "month": s.strftime("%Y-%m"),
            "revenue": _money(paid_by.get(s, zero) - ref_by.get(s, zero)),
        }
        for s in starts
    ]


def _tickets_by_month(months: int = 6) -> list[dict]:
    """Intake vs. throughput: tickets opened and tickets resolved per month."""
    starts = _month_starts(months)
    # created_at/resolved_at are DateTimeFields, so TruncMonth yields aware
    # datetimes — .date() aligns them with the date keys in `starts`.
    opened = (
        Ticket.objects.filter(created_at__date__gte=starts[0])
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(count=Count("id"))
    )
    resolved = (
        Ticket.objects.filter(resolved_at__date__gte=starts[0])
        .annotate(month=TruncMonth("resolved_at"))
        .values("month")
        .annotate(count=Count("id"))
    )
    opened_by = {r["month"].date(): r["count"] for r in opened}
    resolved_by = {r["month"].date(): r["count"] for r in resolved}
    return [
        {
            "month": s.strftime("%Y-%m"),
            "opened": opened_by.get(s, 0),
            "resolved": resolved_by.get(s, 0),
        }
        for s in starts
    ]


def _invoice_aging() -> dict:
    """
    The classic AR aging report: how much owed money is how late. One
    conditional-Sum query — five buckets, one table scan.
    """
    today = timezone.localdate()

    def bucket(cond: Q):
        return Sum(BALANCE_DUE, filter=OWING & cond, output_field=MONEY)

    data = Invoice.objects.aggregate(
        current=bucket(Q(due_date__gte=today)),
        days_1_30=bucket(Q(due_date__lt=today, due_date__gte=today - timedelta(days=30))),
        days_31_60=bucket(
            Q(due_date__lt=today - timedelta(days=30), due_date__gte=today - timedelta(days=60))
        ),
        days_61_90=bucket(
            Q(due_date__lt=today - timedelta(days=60), due_date__gte=today - timedelta(days=90))
        ),
        days_over_90=bucket(Q(due_date__lt=today - timedelta(days=90))),
    )
    return {k: _money(v) for k, v in data.items()}


def get_charts(user) -> dict:
    """
    Chart datasets, each shaped exactly as a chart library wants them
    (list of points) — the frontend maps, it never re-aggregates.
    """
    charts = {
        "project_status": _project_status_chart(user),
        "tickets_by_month": _tickets_by_month(),
        "as_of": timezone.now().isoformat(),
    }
    if user.role != User.Role.STAFF:
        charts["revenue_by_month"] = _revenue_by_month()
        charts["invoice_aging"] = _invoice_aging()
    return charts
