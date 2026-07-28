"""
Query-string filters for /api/v1/tickets/ (django-filter).

The support queue lives or dies by its filters: "my open urgent tickets",
"everything overdue", "unassigned queue". Exact narrowing here; fuzzy text
is ?search= (SearchFilter) in the viewset.
"""

import django_filters
from django.db.models import Q
from django.utils import timezone

from .models import Ticket, TicketPriority


class TicketFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(choices=Ticket.Status.choices)
    priority = django_filters.ChoiceFilter(choices=TicketPriority.choices)
    client = django_filters.NumberFilter()
    category = django_filters.NumberFilter()
    assignee = django_filters.NumberFilter()
    is_escalated = django_filters.BooleanFilter()
    # ?unassigned=true — the pickup queue. A dedicated flag because
    # ?assignee=null isn't expressible with NumberFilter.
    unassigned = django_filters.BooleanFilter(field_name="assignee", lookup_expr="isnull")
    # ?overdue=true — every unfinished ticket past EITHER deadline. Computed
    # against now() at query time; mirrors the model's is_*_overdue properties
    # in SQL (the properties can't be used in a WHERE clause — they're Python).
    overdue = django_filters.BooleanFilter(method="filter_overdue")
    created_after = django_filters.DateFilter(field_name="created_at", lookup_expr="date__gte")
    created_before = django_filters.DateFilter(field_name="created_at", lookup_expr="date__lte")

    class Meta:
        model = Ticket
        fields = [
            "status",
            "priority",
            "client",
            "category",
            "assignee",
            "is_escalated",
            "unassigned",
            "overdue",
            "created_after",
            "created_before",
        ]

    def filter_overdue(self, queryset, name, value):
        now = timezone.now()
        breached = Q(status__in=Ticket.OPEN_STATUSES) & (
            Q(first_response_at=None, first_response_due_at__lt=now) | Q(resolution_due_at__lt=now)
        )
        return queryset.filter(breached) if value else queryset.exclude(breached)
