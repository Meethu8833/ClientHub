"""
Query-string filters for the teams app (django-filter, §6).
"""

import django_filters

from .models import Team, TeamMembership, TimeOff


class TeamFilter(django_filters.FilterSet):
    # ?department=2 — the department page's team list
    department = django_filters.NumberFilter()
    # ?member=7 — "which teams is Dev on" (spans the M2M join)
    member = django_filters.NumberFilter(field_name="members")

    class Meta:
        model = Team
        fields = ["department", "member"]


class TeamMembershipFilter(django_filters.FilterSet):
    """?user=7 — one person's seats and allocations across all teams."""

    team = django_filters.NumberFilter()
    user = django_filters.NumberFilter()

    class Meta:
        model = TeamMembership
        fields = ["team", "user"]


class TimeOffFilter(django_filters.FilterSet):
    """
    The absence calendar: ?from_date=&to_date= returns every entry that
    OVERLAPS the window (ends after it opens AND starts before it closes) —
    not just entries fully inside it.
    """

    user = django_filters.NumberFilter()
    type = django_filters.ChoiceFilter(choices=TimeOff.Type.choices)
    from_date = django_filters.DateFilter(field_name="end_date", lookup_expr="gte")
    to_date = django_filters.DateFilter(field_name="start_date", lookup_expr="lte")

    class Meta:
        model = TimeOff
        fields = ["user", "type", "from_date", "to_date"]
