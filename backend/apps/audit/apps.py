from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.audit"

    def ready(self):
        """
        ready() runs once per process after ALL apps are loaded — the only
        safe place to import models from other apps and attach signal
        handlers to them. Importing signals at module top would run during
        app loading, when those models may not exist yet.
        """
        from . import signals

        signals.connect_model_signals()
