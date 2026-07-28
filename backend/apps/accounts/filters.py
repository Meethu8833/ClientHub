"""
Declarative query-string filters for /api/v1/users/ (django-filter).

Filtering (exact-match narrowing) is distinct from search (fuzzy text,
SearchFilter) and sorting (OrderingFilter) — the viewset combines all three.
"""

import django_filters

from .models import User


class UserFilter(django_filters.FilterSet):
    # ?role=manager — ChoiceFilter rejects values outside Role.choices
    role = django_filters.ChoiceFilter(choices=User.Role.choices)
    # ?is_active=true / false — accepts true/false/1/0
    is_active = django_filters.BooleanFilter()
    # ?joined_after=2026-01-01&joined_before=2026-06-30 (inclusive bounds)
    joined_after = django_filters.DateFilter(field_name="date_joined", lookup_expr="date__gte")
    joined_before = django_filters.DateFilter(field_name="date_joined", lookup_expr="date__lte")

    class Meta:
        model = User
        fields = ["role", "is_active", "joined_after", "joined_before"]
