from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.documents"

    def ready(self):
        # Import for side effects: registers the post_delete file-cleanup
        # receiver. Without this import the signal module never loads.
        from . import signals  # noqa: F401
