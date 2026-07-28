"""Query-string filters for the notification list."""

import django_filters

from .models import Notification


class NotificationFilter(django_filters.FilterSet):
    # ?unread=true → only unread. Mapped onto the read_at NULL-ness so the
    # API speaks in the user's vocabulary, not the schema's.
    unread = django_filters.BooleanFilter(field_name="read_at", lookup_expr="isnull")

    class Meta:
        model = Notification
        fields = ["category", "unread"]
