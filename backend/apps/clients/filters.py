"""
Query-string filters for /api/v1/clients/ (django-filter).

Filtering = exact narrowing (?status=active), search = fuzzy text
(?search=acme, SearchFilter), sorting = ?ordering= (OrderingFilter).
The viewset combines all three.
"""

import django_filters

from .models import Client


class ClientFilter(django_filters.FilterSet):
    # ?status=prospect — ChoiceFilter 400s on values outside the enum
    status = django_filters.ChoiceFilter(choices=Client.Status.choices)
    # ?industry=fintech — case-insensitive containment, "Fintech"/"FinTech" both hit
    industry = django_filters.CharFilter(lookup_expr="icontains")
    city = django_filters.CharFilter(lookup_expr="icontains")
    # ?account_manager=4 — "show me Maya's book of business"
    account_manager = django_filters.NumberFilter()
    # ?created_after=2026-01-01&created_before=2026-06-30 (inclusive)
    created_after = django_filters.DateFilter(field_name="created_at", lookup_expr="date__gte")
    created_before = django_filters.DateFilter(field_name="created_at", lookup_expr="date__lte")

    class Meta:
        model = Client
        fields = [
            "status",
            "industry",
            "city",
            "account_manager",
            "created_after",
            "created_before",
        ]
