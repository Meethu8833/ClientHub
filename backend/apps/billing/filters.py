"""
Query-string filters for /api/v1/invoices/ (django-filter).

The billing screen lives on these: "what's unpaid", "what's overdue",
"everything for client 7 this quarter". Exact narrowing here; fuzzy text is
?search= (SearchFilter) in the viewset.
"""

import django_filters
from django.utils import timezone

from .models import Invoice, Payment


class InvoiceFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(choices=Invoice.Status.choices)
    client = django_filters.NumberFilter()
    project = django_filters.NumberFilter()
    invoice_number = django_filters.CharFilter(lookup_expr="iexact")
    # ?unpaid=true — every invoice still owing money, regardless of overdue.
    unpaid = django_filters.BooleanFilter(method="filter_unpaid")
    # ?overdue=true — owing AND past due: the dunning list. Mirrors the
    # model's is_overdue property in SQL — a property can't be a WHERE clause.
    overdue = django_filters.BooleanFilter(method="filter_overdue")
    # ?due_before=2026-08-15 — cash-flow forecasting: what should land by then.
    due_before = django_filters.DateFilter(field_name="due_date", lookup_expr="lte")
    min_total = django_filters.NumberFilter(field_name="grand_total", lookup_expr="gte")
    max_total = django_filters.NumberFilter(field_name="grand_total", lookup_expr="lte")
    issued_after = django_filters.DateFilter(field_name="issue_date", lookup_expr="gte")
    issued_before = django_filters.DateFilter(field_name="issue_date", lookup_expr="lte")

    class Meta:
        model = Invoice
        fields = [
            "status",
            "client",
            "project",
            "invoice_number",
            "unpaid",
            "overdue",
            "due_before",
            "min_total",
            "max_total",
            "issued_after",
            "issued_before",
        ]

    def filter_unpaid(self, queryset, name, value):
        owing = {"status__in": Invoice.OWING_STATUSES}
        return queryset.filter(**owing) if value else queryset.exclude(**owing)

    def filter_overdue(self, queryset, name, value):
        lapsed = {
            "status__in": Invoice.OWING_STATUSES,
            "due_date__lt": timezone.localdate(),
        }
        return queryset.filter(**lapsed) if value else queryset.exclude(**lapsed)


class PaymentFilter(django_filters.FilterSet):
    """
    The payments register / reconciliation screen: "everything that hit the
    bank in June, unmatched first" is
    ?status=completed&received_after=2026-06-01&received_before=2026-06-30
    &reconciled=false — each statement line is then found by amount/reference.
    """

    invoice = django_filters.NumberFilter()
    client = django_filters.NumberFilter(field_name="invoice__client")
    method = django_filters.ChoiceFilter(choices=Payment.Method.choices)
    status = django_filters.ChoiceFilter(choices=Payment.Status.choices)
    # ?reconciled=false — the working list; a NULL check, since the stamp IS
    # the flag (one truth, no separate boolean to fall out of sync).
    reconciled = django_filters.BooleanFilter(
        field_name="reconciled_at", lookup_expr="isnull", exclude=True
    )
    reference = django_filters.CharFilter(lookup_expr="icontains")
    received_after = django_filters.DateFilter(field_name="received_on", lookup_expr="gte")
    received_before = django_filters.DateFilter(field_name="received_on", lookup_expr="lte")
    min_amount = django_filters.NumberFilter(field_name="amount", lookup_expr="gte")
    max_amount = django_filters.NumberFilter(field_name="amount", lookup_expr="lte")

    class Meta:
        model = Payment
        fields = [
            "invoice",
            "client",
            "method",
            "status",
            "reconciled",
            "reference",
            "received_after",
            "received_before",
            "min_amount",
            "max_amount",
        ]
