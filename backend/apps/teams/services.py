"""
Team-management services (§11): logic that spans models — the 100 % allocation
budget and the capacity report — lives here so views stay thin and the math
is unit-testable without HTTP.
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum

from apps.projects.models import TimeEntry

from .models import TeamMembership, TimeOff

# One year — keeps the day-walking loops bounded (the view rejects bigger windows).
MAX_REPORT_DAYS = 366


def user_total_allocation(user, exclude=None):
    """
    Summed allocation % across the user's seats on ACTIVE teams. Soft-deleted
    teams keep their membership rows but stop counting — disbanding a team
    frees its people's share. `exclude` skips the membership being edited so
    "change 60 → 80" doesn't count the old 60 against itself.
    """
    qs = TeamMembership.objects.filter(user=user, team__is_active=True)
    if exclude is not None:
        qs = qs.exclude(pk=exclude.pk)
    return qs.aggregate(total=Sum("allocation_percent"))["total"] or 0


def workdays_between(start, end):
    """
    Inclusive count of weekdays (Mon–Fri). Weekends never count as capacity
    or as consumed leave. Public holidays are a future refinement — they need
    a per-country holiday calendar table.
    """
    days = 0
    current = start
    while current <= end:
        if current.weekday() < 5:  # 0=Mon … 4=Fri
            days += 1
        current += timedelta(days=1)
    return days


def _money_round(value):
    return value.quantize(Decimal("0.01"))


def team_capacity_report(*, team, start, end):
    """
    The capacity report for one team over [start, end] (inclusive).

    Per member:
      gross_capacity_hours  = weekly_capacity × allocation% × workdays ÷ 5
                              (their slice of the week promised to THIS team)
      time_off_days         = absence weekdays clamped to the window
      net_capacity_hours    = gross − time off, scaled by the same allocation
      logged_hours          = Σ TimeEntry.hours in the window — the whole
                              person's logged work, NOT per team: a time entry
                              belongs to a project, and projects don't map to
                              teams, so a per-team split does not exist.
      utilization_percent   = logged ÷ the PERSON's net capacity (all teams).
                              Dividing whole-person hours by one team's slice
                              would show 200 % for anyone on two teams.

    Everything is computed in exactly three queries regardless of team size
    (memberships, one grouped TimeEntry aggregate, one TimeOff fetch) — the
    same N+1 discipline as the viewset annotations (§6).
    """
    memberships = list(team.memberships.select_related("user"))
    user_ids = [m.user_id for m in memberships]
    workdays = workdays_between(start, end)

    logged_by_user = {
        row["user_id"]: row["total"]
        for row in TimeEntry.objects.filter(user_id__in=user_ids, worked_on__range=(start, end))
        .values("user_id")
        .annotate(total=Sum("hours"))
    }

    # Overlap filter: an absence touches the window iff it starts before the
    # window ends AND ends after the window starts. Days outside the window
    # are clamped away — a 3-week vacation only costs the days inside.
    off_days_by_user = {}
    absences = TimeOff.objects.filter(
        user_id__in=user_ids, start_date__lte=end, end_date__gte=start
    )
    for off in absences:
        clamped = workdays_between(max(off.start_date, start), min(off.end_date, end))
        off_days_by_user[off.user_id] = off_days_by_user.get(off.user_id, 0) + clamped

    members = []
    total_net = Decimal("0")
    total_logged = Decimal("0")
    for membership in memberships:
        user = membership.user
        weekly = user.weekly_capacity_hours  # Decimal — money-adjacent math (§11)
        share = Decimal(membership.allocation_percent) / 100
        daily = weekly / 5
        off_days = off_days_by_user.get(user.id, 0)

        gross = weekly * workdays / 5 * share
        net = max(gross - daily * off_days * share, Decimal("0"))
        person_net = max(weekly * workdays / 5 - daily * off_days, Decimal("0"))
        logged = logged_by_user.get(user.id) or Decimal("0")

        members.append(
            {
                "user": {
                    "id": user.id,
                    "name": user.get_full_name() or user.email,
                    "email": user.email,
                },
                "allocation_percent": membership.allocation_percent,
                "gross_capacity_hours": _money_round(gross),
                "time_off_days": off_days,
                "net_capacity_hours": _money_round(net),
                "logged_hours": _money_round(logged),
                "utilization_percent": (
                    round(float(logged / person_net * 100), 1) if person_net else None
                ),
            }
        )
        total_net += net
        total_logged += logged

    return {
        "team": team.pk,
        "from": start,
        "to": end,
        "workdays": workdays,
        "members": members,
        "totals": {
            "net_capacity_hours": _money_round(total_net),
            "logged_hours": _money_round(total_logged),
        },
    }
