"""Development settings — convenience over lockdown, but same DB engine as prod."""

from .base import *  # noqa: F403

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# No HTTPS locally, so the refresh cookie can't be Secure-only in dev.
REFRESH_TOKEN_COOKIE_SECURE = False

# Emails print to the runserver console instead of actually sending.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Browsable API in dev only: lets you explore endpoints from the browser.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_RENDERER_CLASSES": (
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ),
}
