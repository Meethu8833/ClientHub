"""
Query-string filters for /api/v1/quotations/ (django-filter).

The sales pipeline lives on these: "my drafts", "everything awaiting my
approval", "sent quotes expiring this week". Exact narrowing here; fuzzy
text is ?search= (SearchFilter) in the viewset.
"""

import django_filters
from django.utils import timezone

from .models import Quotation


class QuotationFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(choices=Quotation.Status.choices)
    client = django_filters.NumberFilter()
    created_by = django_filters.NumberFilter()
    quote_number = django_filters.CharFilter(lookup_expr="iexact")
    # ?expiring_before=2026-08-15 — sent quotes whose window closes by then;
    # the "chase these clients this week" list.
    expiring_before = django_filters.DateFilter(method="filter_expiring_before")
    # ?expired=true — sent quotes already past their date (sweep may not have
    # run yet). Mirrors the model's is_expired property in SQL — a Python
    # property can't be used in a WHERE clause.
    expired = django_filters.BooleanFilter(method="filter_expired")
    min_total = django_filters.NumberFilter(field_name="grand_total", lookup_expr="gte")
    max_total = django_filters.NumberFilter(field_name="grand_total", lookup_expr="lte")
    created_after = django_filters.DateFilter(field_name="created_at", lookup_expr="date__gte")
    created_before = django_filters.DateFilter(field_name="created_at", lookup_expr="date__lte")

    class Meta:
        model = Quotation
        fields = [
            "status",
            "client",
            "created_by",
            "quote_number",
            "expiring_before",
            "expired",
            "min_total",
            "max_total",
            "created_after",
            "created_before",
        ]

    def filter_expiring_before(self, queryset, name, value):
        return queryset.filter(status=Quotation.Status.SENT, valid_until__lte=value)

    def filter_expired(self, queryset, name, value):
        lapsed = {"status": Quotation.Status.SENT, "valid_until__lt": timezone.localdate()}
        return queryset.filter(**lapsed) if value else queryset.exclude(**lapsed)
