from django.apps import AppConfig


class DashboardConfig(AppConfig):
    """
    A read-only app: no models, no migrations. It owns nothing in the
    database — it only aggregates what the other apps own.
    """

    name = "apps.dashboard"
