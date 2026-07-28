"""
Report builders (docs/reports-module.md).

Every report here produces the same neutral shape — a ReportTable: typed
columns, rows of native Python values, an optional totals row, and an echo of
the filters that produced it. The views and the exporters consume ONLY that
shape, so:

    new report   = one builder function in this file
    new format   = one function in exporters.py

and the two never need to know about each other (the whole point).

Aggregation rules follow the dashboard service: the DATABASE does the math
(GROUP BY via .values().annotate(), conditional counts via filter=Q(...)),
Python only zero-fills gaps and shapes dicts. Rows keep native Decimals —
JSON stringifies them in as_dict() (floats corrupt money), while Excel gets
the raw numbers so cells stay summable in a spreadsheet.

Role scoping mirrors §8 exactly, same as the dashboard: a report must never
show a number the caller couldn't reach by paging the source endpoint.
Revenue is manager/admin-only (enforced in the view — STAFF get 403);
time entries are scoped to the caller's own rows for STAFF; the ticket
queue is shared by every role.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db.models import Avg, Count, DecimalField, DurationField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from apps.accounts.models import User
from apps.billing.models import Invoice, Payment, Refund
from apps.projects.models import TimeEntry
from apps.tickets.models import Ticket, TicketPriority

MONEY = DecimalField(max_digits=14, decimal_places=2)

# Same expression the dashboard uses: what an invoice still owes, in SQL.
BALANCE_DUE = F("grand_total") - F("amount_paid") + F("amount_refunded")
OWING = Q(status__in=Invoice.OWING_STATUSES)

# "Real" invoices for revenue purposes: DRAFT is not yet a bill, VOID is a
# retracted mistake — counting either would inflate the invoiced figure.
BILLED = Q(status__in=[Invoice.Status.ISSUED, Invoice.Status.PARTIALLY_PAID, Invoice.Status.PAID])

ZERO = Decimal("0")
CENT = Decimal("0.01")


# ---------------------------------------------------------------------------
# The contract every report produces and every exporter consumes.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Column:
    """
    One report column. `kind` drives formatting downstream:
    text → left-aligned string; int → count; money/hours → 2-decimal number
    (Excel number format, PDF right-alignment, JSON string).
    """

    key: str
    label: str
    kind: str = "text"  # "text" | "int" | "money" | "hours"


@dataclass
class ReportTable:
    slug: str  # machine name, used in filenames: "revenue-report"
    title: str  # human name, used as sheet/PDF heading
    columns: list[Column]
    rows: list[dict]  # native types keyed by Column.key
    totals: dict | None = None  # same keys; None where a total is meaningless
    filters: dict = field(default_factory=dict)  # JSON-safe echo of the params

    NUMERIC = ("money", "hours")

    def as_dict(self) -> dict:
        """
        The JSON view. Decimals leave as quantized strings ("1234.50") —
        JSON has no Decimal and floats corrupt money (house rule, same as
        /payments/summary/ and the dashboard). None stays null: "no data"
        is not the same fact as zero.
        """

        def clean(value):
            if isinstance(value, Decimal):
                return str(value.quantize(CENT))
            return value

        return {
            "title": self.title,
            "filters": self.filters,
            "columns": [{"key": c.key, "label": c.label, "kind": c.kind} for c in self.columns],
            "rows": [{k: clean(v) for k, v in row.items()} for row in self.rows],
            "totals": {k: clean(v) for k, v in self.totals.items()} if self.totals else None,
            "generated_at": timezone.now().isoformat(),
        }


def _month_starts(date_from: date, date_to: date) -> list[date]:
    """First day of every month the window touches, oldest first."""
    y, m = date_from.year, date_from.month
    out = []
    while (y, m) <= (date_to.year, date_to.month):
        out.append(date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _window(params: dict) -> dict:
    """The JSON-safe filter echo every report starts from."""
    return {
        "date_from": params["date_from"].isoformat(),
        "date_to": params["date_to"].isoformat(),
    }


# ---------------------------------------------------------------------------
# Revenue report (manager/admin only — the view enforces the 403).
# ---------------------------------------------------------------------------


def revenue_report(params: dict) -> ReportTable:
    """
    Money story for a period, from three tables:

      invoiced   what we billed        (invoices by issue_date, VOID/DRAFT out)
      collected  what actually landed  (completed payments by received_on)
      refunded   what went back out    (refunds by refunded_on)
      net        collected - refunded  — cash truth for the period

    grouped by month (trend) or by client (who the money comes from).
    Invoiced and collected deliberately DON'T reconcile inside one bucket:
    an invoice issued in March is often paid in April. That timing gap is
    real information, not a bug.
    """
    date_from, date_to = params["date_from"], params["date_to"]
    client_id = params.get("client")

    invoices = Invoice.objects.filter(BILLED, issue_date__range=(date_from, date_to))
    payments = Payment.objects.filter(
        status=Payment.Status.COMPLETED, received_on__range=(date_from, date_to)
    )
    refunds = Refund.objects.filter(refunded_on__range=(date_from, date_to))
    if client_id:
        invoices = invoices.filter(client_id=client_id)
        payments = payments.filter(invoice__client_id=client_id)
        refunds = refunds.filter(payment__invoice__client_id=client_id)

    filters = _window(params) | {"client": client_id, "group_by": params["group_by"]}

    if params["group_by"] == "client":
        rows = _revenue_by_client(invoices, payments, refunds)
        first_col = Column("client", "Client")
    else:
        rows = _revenue_by_month(invoices, payments, refunds, date_from, date_to)
        first_col = Column("month", "Month")

    totals = {
        first_col.key: "Total",
        "invoiced": sum((r["invoiced"] for r in rows), ZERO),
        "collected": sum((r["collected"] for r in rows), ZERO),
        "refunded": sum((r["refunded"] for r in rows), ZERO),
        "net": sum((r["net"] for r in rows), ZERO),
    }
    return ReportTable(
        slug="revenue-report",
        title="Revenue Report",
        columns=[
            first_col,
            Column("invoiced", "Invoiced", "money"),
            Column("collected", "Collected", "money"),
            Column("refunded", "Refunded", "money"),
            Column("net", "Net revenue", "money"),
        ],
        rows=rows,
        totals=totals,
        filters=filters,
    )


def _revenue_by_month(invoices, payments, refunds, date_from, date_to) -> list[dict]:
    """
    Three GROUP-BY-month queries (different tables, different date columns —
    a UNION would buy nothing but obscurity), merged and zero-filled in
    Python: GROUP BY only returns months that have rows, but a report reads
    wrong with holes in the axis.
    """

    def by_month(qs, date_field, expr):
        rows = qs.annotate(month=TruncMonth(date_field)).values("month").annotate(total=expr)
        return {r["month"]: r["total"] or ZERO for r in rows}

    invoiced = by_month(invoices, "issue_date", Sum("grand_total"))
    collected = by_month(payments, "received_on", Sum("amount"))
    refunded = by_month(refunds, "refunded_on", Sum("amount"))

    out = []
    for start in _month_starts(date_from, date_to):
        c, r = collected.get(start, ZERO), refunded.get(start, ZERO)
        out.append(
            {
                "month": start.strftime("%Y-%m"),
                "invoiced": invoiced.get(start, ZERO),
                "collected": c,
                "refunded": r,
                "net": c - r,
            }
        )
    return out


def _revenue_by_client(invoices, payments, refunds) -> list[dict]:
    """Same three queries GROUPed BY client, plus what those invoices still owe."""
    inv = invoices.values("client_id", "client__name").annotate(
        invoiced=Sum("grand_total"),
        outstanding=Sum(BALANCE_DUE, filter=OWING, output_field=MONEY),
    )
    paid = payments.values("invoice__client_id").annotate(total=Sum("amount"))
    ref = refunds.values("payment__invoice__client_id").annotate(total=Sum("amount"))

    merged: dict[int, dict] = {}

    def slot(cid, name=""):
        return merged.setdefault(
            cid,
            {
                "client": name,
                "invoiced": ZERO,
                "collected": ZERO,
                "refunded": ZERO,
                "net": ZERO,
                "outstanding": ZERO,
            },
        )

    for r in inv:
        row = slot(r["client_id"], r["client__name"])
        row["client"] = r["client__name"]
        row["invoiced"] = r["invoiced"] or ZERO
        row["outstanding"] = r["outstanding"] or ZERO
    for r in paid:
        slot(r["invoice__client_id"])["collected"] = r["total"] or ZERO
    for r in ref:
        slot(r["payment__invoice__client_id"])["refunded"] = r["total"] or ZERO

    # A client can appear via payments only (invoice issued before the
    # window) — fetch the missing names in one query rather than N.
    nameless = [cid for cid, row in merged.items() if not row["client"]]
    if nameless:
        from apps.clients.models import Client

        for cid, name in Client.objects.filter(id__in=nameless).values_list("id", "name"):
            merged[cid]["client"] = name

    for row in merged.values():
        row["net"] = row["collected"] - row["refunded"]
    return sorted(merged.values(), key=lambda r: r["client"].lower())


# ---------------------------------------------------------------------------
# Time tracking report (all roles; STAFF see only their own entries — §8).
# ---------------------------------------------------------------------------


def time_report(user, params: dict) -> ReportTable:
    """
    Logged hours grouped by project (where did the effort go) or by user
    (who spent it), over TimeEntry.worked_on — the day the work HAPPENED,
    not the day it was typed in.
    """
    qs = TimeEntry.objects.filter(worked_on__range=(params["date_from"], params["date_to"]))
    if user.role == User.Role.STAFF:
        # §8: "time entries — own only". The scoping wins over any ?user=
        # param a curious STAFF might append; managers may query anyone.
        qs = qs.filter(user=user)
    elif params.get("user"):
        qs = qs.filter(user_id=params["user"])
    if params.get("project"):
        qs = qs.filter(task__project_id=params["project"])

    filters = _window(params) | {
        "project": params.get("project"),
        "user": user.id if user.role == User.Role.STAFF else params.get("user"),
        "group_by": params["group_by"],
    }

    if params["group_by"] == "user":
        grouped = (
            qs.values("user__first_name", "user__last_name", "user__email")
            .annotate(entries=Count("id"), hours=Sum("hours"))
            .order_by("user__first_name", "user__last_name")
        )
        rows = [
            {
                "user": f"{r['user__first_name']} {r['user__last_name']}".strip()
                or r["user__email"],
                "entries": r["entries"],
                "hours": r["hours"] or ZERO,
            }
            for r in grouped
        ]
        first_col = Column("user", "Team member")
    else:
        grouped = (
            qs.values("task__project__name", "task__project__client__name")
            .annotate(entries=Count("id"), hours=Sum("hours"))
            .order_by("task__project__name")
        )
        rows = [
            {
                "project": r["task__project__name"],
                "client": r["task__project__client__name"],
                "entries": r["entries"],
                "hours": r["hours"] or ZERO,
            }
            for r in grouped
        ]
        first_col = Column("project", "Project")

    columns = [first_col]
    if params["group_by"] == "project":
        columns.append(Column("client", "Client"))
    columns += [Column("entries", "Entries", "int"), Column("hours", "Hours", "hours")]

    totals = {
        first_col.key: "Total",
        "entries": sum(r["entries"] for r in rows),
        "hours": sum((r["hours"] for r in rows), ZERO),
    }
    return ReportTable(
        slug="time-report",
        title="Time Tracking Report",
        columns=columns,
        rows=rows,
        totals=totals,
        filters=filters,
    )


# ---------------------------------------------------------------------------
# Ticket SLA report (all roles — the ticket queue is shared).
# ---------------------------------------------------------------------------


def ticket_report(params: dict) -> ReportTable:
    """
    Support performance per priority for tickets CREATED in the window:
    volume in/out, both SLA clocks (first response, resolution), and the
    average time-to-resolve. One GROUP-BY-priority query — the conditional-
    aggregation trick again, this time with an Avg over a datetime
    difference (Postgres does interval arithmetic natively).
    """
    now = timezone.now()
    qs = Ticket.objects.filter(created_at__date__range=(params["date_from"], params["date_to"]))
    if params.get("client"):
        qs = qs.filter(client_id=params["client"])

    # Breached = answered late, OR still unanswered past the deadline.
    # No deadline stamped (no SLA policy) → no promise → no breach.
    fr_breached = Q(first_response_due_at__isnull=False) & (
        Q(first_response_at__gt=F("first_response_due_at"))
        | Q(first_response_at__isnull=True, first_response_due_at__lt=now)
    )
    res_breached = Q(resolution_due_at__isnull=False) & (
        Q(resolved_at__gt=F("resolution_due_at"))
        | Q(resolved_at__isnull=True, resolution_due_at__lt=now)
    )
    resolution_time = ExpressionWrapper(
        F("resolved_at") - F("created_at"), output_field=DurationField()
    )

    grouped = {
        r["priority"]: r
        for r in qs.values("priority").annotate(
            created=Count("id"),
            resolved=Count("id", filter=Q(resolved_at__isnull=False)),
            fr_breached=Count("id", filter=fr_breached),
            res_breached=Count("id", filter=res_breached),
            avg_resolution=Avg(resolution_time, filter=Q(resolved_at__isnull=False)),
        )
    }

    rows = []
    for prio in TicketPriority:  # fixed business order: low → urgent
        r = grouped.get(prio.value)
        if r is None:
            continue  # unlike a time axis, an absent priority is just noise
        avg = r["avg_resolution"]
        rows.append(
            {
                "priority": prio.label,
                "created": r["created"],
                "resolved": r["resolved"],
                "first_response_breached": r["fr_breached"],
                "resolution_breached": r["res_breached"],
                # timedelta → Decimal hours; None (nothing resolved) stays
                # None — "no data yet" must not read as "0 hours".
                "avg_resolution_hours": (
                    Decimal(str(avg.total_seconds() / 3600)).quantize(CENT)
                    if avg is not None
                    else None
                ),
            }
        )

    totals = {
        "priority": "Total",
        "created": sum(r["created"] for r in rows),
        "resolved": sum(r["resolved"] for r in rows),
        "first_response_breached": sum(r["first_response_breached"] for r in rows),
        "resolution_breached": sum(r["resolution_breached"] for r in rows),
        "avg_resolution_hours": None,  # an average of averages would lie
    }
    return ReportTable(
        slug="ticket-sla-report",
        title="Ticket SLA Report",
        columns=[
            Column("priority", "Priority"),
            Column("created", "Created", "int"),
            Column("resolved", "Resolved", "int"),
            Column("first_response_breached", "1st response breached", "int"),
            Column("resolution_breached", "Resolution breached", "int"),
            Column("avg_resolution_hours", "Avg resolution (h)", "hours"),
        ],
        rows=rows,
        totals=totals,
        filters=_window(params) | {"client": params.get("client")},
    )
