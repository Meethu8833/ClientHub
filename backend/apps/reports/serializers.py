"""
Query-parameter validation for the report endpoints (docs/reports-module.md).

Reports have no model, so these are plain `serializers.Serializer` classes
used the "other way round": instead of validating a POST body they validate
`request.query_params`. Same machinery — typed fields, defaults, cross-field
checks in validate() — which beats hand-parsing GET params in the view
(silent typos, no 400s, stringly-typed dates).

Not django-filter: a FilterSet narrows a queryset of model rows. Report
parameters aren't row filters — `group_by` picks the SQL GROUP BY column and
`export` picks the response format. A Serializer models "a bag of typed
parameters" honestly.

Every report shares the same date-window contract (defaults: last 12 months,
capped at 5 years so nobody can ask the DB to chew a decade in one request).
"""

from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

EXPORT_JSON, EXPORT_XLSX, EXPORT_PDF = "json", "xlsx", "pdf"

# One year of data by default; hard cap so a typo ("1926-01-01") can't turn
# into a full-table scan on a big installation.
DEFAULT_RANGE_DAYS = 365
MAX_RANGE_DAYS = 366 * 5


class BaseReportParams(serializers.Serializer):
    """Shared window + format params. Subclasses add report-specific knobs."""

    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    export = serializers.ChoiceField(
        choices=(EXPORT_JSON, EXPORT_XLSX, EXPORT_PDF), default=EXPORT_JSON
    )

    def validate(self, attrs):
        # Defaults live here (not in the field declarations) because
        # date_from's default depends on date_to's resolved value.
        attrs.setdefault("date_to", timezone.localdate())
        attrs.setdefault("date_from", attrs["date_to"] - timedelta(days=DEFAULT_RANGE_DAYS))
        if attrs["date_from"] > attrs["date_to"]:
            raise serializers.ValidationError({"date_from": "Must be on or before date_to."})
        if (attrs["date_to"] - attrs["date_from"]).days > MAX_RANGE_DAYS:
            raise serializers.ValidationError(
                {"date_from": f"Range may not exceed {MAX_RANGE_DAYS} days."}
            )
        return attrs


class RevenueReportParams(BaseReportParams):
    client = serializers.IntegerField(required=False, min_value=1)
    group_by = serializers.ChoiceField(choices=("month", "client"), default="month")


class TimeReportParams(BaseReportParams):
    project = serializers.IntegerField(required=False, min_value=1)
    user = serializers.IntegerField(required=False, min_value=1)
    group_by = serializers.ChoiceField(choices=("project", "user"), default="project")


class TicketReportParams(BaseReportParams):
    client = serializers.IntegerField(required=False, min_value=1)
