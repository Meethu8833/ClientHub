"""
Query-string filters for /api/v1/meetings/ (django-filter).

The two real screens are a calendar ("everything between these dates") and
personal agendas ("my upcoming meetings") — exact narrowing here; fuzzy text
is ?search= (SearchFilter) in the viewset.
"""

import django_filters
from django.db.models import Q
from django.utils import timezone

from .models import Meeting


class MeetingFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(choices=Meeting.Status.choices)
    mode = django_filters.ChoiceFilter(choices=Meeting.Mode.choices)
    client = django_filters.NumberFilter()
    project = django_filters.NumberFilter()
    organizer = django_filters.NumberFilter()
    # ?attendee=7 — meetings user 7 is invited to. distinct() because the
    # JOIN to attendees can multiply rows.
    attendee = django_filters.NumberFilter(method="filter_attendee")
    # The calendar range: give me everything STARTING between these dates.
    scheduled_after = django_filters.DateFilter(
        field_name="scheduled_start", lookup_expr="date__gte"
    )
    scheduled_before = django_filters.DateFilter(
        field_name="scheduled_start", lookup_expr="date__lte"
    )
    # ?upcoming=true — the agenda widget: still scheduled, not started yet.
    upcoming = django_filters.BooleanFilter(method="filter_upcoming")
    # ?my=true — meetings I organize OR am invited to, whatever my role.
    my = django_filters.BooleanFilter(method="filter_my")

    class Meta:
        model = Meeting
        fields = [
            "status",
            "mode",
            "client",
            "project",
            "organizer",
            "attendee",
            "scheduled_after",
            "scheduled_before",
            "upcoming",
            "my",
        ]

    def filter_attendee(self, queryset, name, value):
        return queryset.filter(attendees__user_id=value).distinct()

    def filter_upcoming(self, queryset, name, value):
        cond = Q(status=Meeting.Status.SCHEDULED, scheduled_start__gt=timezone.now())
        return queryset.filter(cond) if value else queryset.exclude(cond)

    def filter_my(self, queryset, name, value):
        if not value:
            return queryset
        user = self.request.user
        return queryset.filter(Q(organizer=user) | Q(attendees__user=user)).distinct()
