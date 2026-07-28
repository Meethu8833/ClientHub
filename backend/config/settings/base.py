"""
Base settings shared by every environment.

Anything that differs between dev and prod (DEBUG, hosts, security flags)
lives in dev.py / prod.py. Anything secret or machine-specific comes from
environment variables — never hardcode it here.
"""

from datetime import timedelta
from pathlib import Path

import environ

# BASE_DIR = backend/  (this file is backend/config/settings/base.py)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
# REPO_ROOT = ClientHub/ — where .env and docker-compose.yml live
REPO_ROOT = BASE_DIR.parent

env = environ.Env()
# Load ClientHub/.env if present (in Docker/prod, real env vars are injected
# instead and this file simply doesn't exist).
environ.Env.read_env(REPO_ROOT / ".env")

# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = False  # never default to True; dev.py flips it explicitly
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

# --------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Postgres-only features: SearchVector/SearchQuery/SearchRank lookups and
    # GIN index classes used by global search (apps.search).
    "django.contrib.postgres",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",  # tables for revoked refresh tokens
    "corsheaders",
    "django_filters",
    "drf_spectacular",
]

LOCAL_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.clients",
    "apps.sales",
    "apps.projects",
    "apps.teams",
    "apps.documents",
    "apps.activities",
    "apps.audit",
    "apps.tickets",
    "apps.quotations",
    "apps.billing",
    "apps.meetings",
    "apps.notifications",
    "apps.dashboard",
    "apps.reports",
    "apps.search",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # CORS must run before CommonMiddleware so preflight responses get headers
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Parks the request in a ContextVar so audit signal handlers can read
    # actor/IP without threading the request through every save() call.
    "apps.audit.middleware.AuditContextMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --------------------------------------------------------------------------
# Database — PostgreSQL only (parity between dev and prod)
# --------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB"),
        "USER": env("POSTGRES_USER"),
        "PASSWORD": env("POSTGRES_PASSWORD"),
        "HOST": env("DB_HOST", default="localhost"),
        "PORT": env.int("DB_PORT", default=5432),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------
# Cache — used by the dashboard endpoints and DRF throttling
# --------------------------------------------------------------------------
# LocMem = a dict inside THIS process: free, fast, wiped on restart, and NOT
# shared between processes. Perfect for dev (one runserver process); wrong
# for prod (each gunicorn worker would keep its own copy) — prod.py swaps in
# Redis. Same explicit config Django would default to, but visible > implied.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --------------------------------------------------------------------------
# Django REST Framework
# --------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    # Secure by default: every endpoint requires login unless it opts out.
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.DefaultPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": "20/min",
        "user": "1000/hour",
        # Scoped rates for the sensitive auth endpoints (see accounts/views.py).
        "login": "10/min",
        "password_reset": "5/hour",
        "email_verification": "5/hour",
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# --------------------------------------------------------------------------
# JWT (djangorestframework-simplejwt)
# --------------------------------------------------------------------------
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    # Every refresh issues a NEW refresh token and blacklists the old one,
    # so a stolen refresh token dies the moment the real user refreshes.
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
}

# --------------------------------------------------------------------------
# Refresh-token cookie (ARCHITECTURE.md §7)
# The refresh token never reaches JavaScript: it lives in an HttpOnly cookie
# scoped to the auth URLs only, so it is sent solely to /api/v1/auth/*.
# --------------------------------------------------------------------------
REFRESH_TOKEN_COOKIE = "refresh_token"
REFRESH_TOKEN_COOKIE_PATH = "/api/v1/auth/"
REFRESH_TOKEN_COOKIE_SECURE = True  # HTTPS only; dev.py relaxes this
REFRESH_TOKEN_COOKIE_SAMESITE = "Lax"

# --------------------------------------------------------------------------
# Email — used by password reset & email verification.
# Dev overrides EMAIL_BACKEND to the console backend (prints instead of sends).
# --------------------------------------------------------------------------
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="ClientHub <no-reply@clienthub.local>")

# Where email links point (React app) — reset/verify pages live there.
FRONTEND_URL = env("FRONTEND_URL", default="http://localhost:5173")

# How long a password-reset link stays valid (Django built-in setting).
PASSWORD_RESET_TIMEOUT = 60 * 60  # 1 hour
# How long an email-verification link stays valid (our own setting).
EMAIL_VERIFICATION_TIMEOUT = 60 * 60 * 24  # 24 hours

# --------------------------------------------------------------------------
# Audit logging (apps.audit)
# --------------------------------------------------------------------------
# Models whose create/update/delete are recorded automatically via signals.
# Business-critical records only: high-churn operational rows (Task, Note,
# TimeEntry) would bury the signal in noise — their history lives in the
# Activity timeline instead.
AUDITED_MODELS = [
    "accounts.User",
    "clients.Client",
    "clients.Contact",
    "projects.Project",
    "billing.Invoice",
    "billing.Payment",
    "billing.Refund",
]
# Field names never diffed or stored: secrets and machine-churn columns.
AUDIT_EXCLUDED_FIELDS = ["password", "last_login", "created_at", "updated_at"]

# --------------------------------------------------------------------------
# API schema / docs (drf-spectacular)
# --------------------------------------------------------------------------
SPECTACULAR_SETTINGS = {
    "TITLE": "ClientHub CRM API",
    "DESCRIPTION": "Client & Project Management System for IT service companies.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# --------------------------------------------------------------------------
# CORS — which browser origins may call this API
# --------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=["http://localhost:5173"])

# --------------------------------------------------------------------------
# i18n / tz
# --------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True  # store everything in UTC; convert at the edge

# --------------------------------------------------------------------------
# Static & media
# --------------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"  # collectstatic target (prod)

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"  # user uploads (dev: local disk)

# Django 4.2+ storage registry. This IS the default — written out so the
# swap point is visible: prod.py replaces "default" with S3 when USE_S3=True,
# and no application code changes (models call storage through FileField).
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# --------------------------------------------------------------------------
# Private document downloads (ARCHITECTURE.md §9)
# Empty (dev): Django streams files itself via FileResponse.
# Prod: set to the internal Nginx location prefix (e.g. "/internal-media/")
# and add a matching `location /internal-media/ { internal; alias …; }` —
# Django then answers with X-Accel-Redirect and Nginx streams the bytes.
# --------------------------------------------------------------------------
DOCUMENT_X_ACCEL_PREFIX = env("DOCUMENT_X_ACCEL_PREFIX", default="")
