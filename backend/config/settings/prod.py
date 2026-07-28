"""Production settings — everything locked down, JSON only, HTTPS assumed."""

from .base import *  # noqa: F403

DEBUG = False

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")  # noqa: F405 — required, no default

# API responses are JSON only (no browsable HTML API in prod).
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
}

# --- Security hardening (Nginx terminates TLS and forwards the scheme) ---
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30  # 30 days; raise once stable
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# --- Cache: Redis when configured (shared across gunicorn workers) ---
# base.py's LocMem is per-process — with N workers, N private caches: the
# dashboard would recompute per worker and TTLs would drift. Redis gives one
# shared cache. Left optional so a single-worker pilot deploy still boots.
if env("REDIS_URL", default=""):  # noqa: F405
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": env("REDIS_URL"),  # noqa: F405 — e.g. redis://redis:6379/1
        }
    }

# --- Media storage: local volume by default, S3 when scale demands (§9) ---
# The swap is settings-only: FileField talks to whatever "default" storage
# is registered, so uploads/downloads/signals/sweep all follow automatically.
if env.bool("USE_S3", default=False):  # noqa: F405
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "bucket_name": env("AWS_STORAGE_BUCKET_NAME"),  # noqa: F405
                "region_name": env("AWS_S3_REGION_NAME", default=None),  # noqa: F405
                # Set for S3-compatible providers (MinIO, DO Spaces, R2);
                # leave unset for real AWS.
                "endpoint_url": env("AWS_S3_ENDPOINT_URL", default=None),  # noqa: F405
                # None lets boto3 fall back to the IAM instance role — the
                # preferred setup on EC2/ECS: no long-lived keys in env at all.
                "access_key": env("AWS_ACCESS_KEY_ID", default=None),  # noqa: F405
                "secret_key": env("AWS_SECRET_ACCESS_KEY", default=None),  # noqa: F405
                # THE security posture: objects are private; every .url() is a
                # presigned link that expires in 5 minutes (§9: media is never
                # publicly served — same rule as X-Accel, different mechanism).
                "default_acl": "private",
                "querystring_auth": True,
                "querystring_expire": 300,
                # Never overwrite on name collision (our UUID names make
                # collisions near-impossible; this is defense in depth).
                "file_overwrite": False,
            },
        },
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
