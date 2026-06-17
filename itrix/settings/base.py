"""
Base settings shared by every environment.

Environment-specific modules (development.py / production.py) import * from here
and override what they need. All values are read from the environment with safe
defaults so the project boots even before keys are present (feature flags gate the
external integrations).
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────
# settings/base.py -> settings -> itrix -> <repo root>
BASE_DIR = Path(__file__).resolve().parent.parent.parent


# ─────────────────────────────────────────────────────────────────────────────
# Small env helpers (kept local so base.py has no extra import dependencies)
# ─────────────────────────────────────────────────────────────────────────────
def env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


def env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_list(key: str, default: str = "") -> list[str]:
    raw = os.environ.get(key, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# ─────────────────────────────────────────────────────────────────────────────
# Core security
# ─────────────────────────────────────────────────────────────────────────────
SECRET_KEY = env("SECRET_KEY", "dev-insecure-change-me")
DEBUG = env_bool("DEBUG", False)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")


# ─────────────────────────────────────────────────────────────────────────────
# Applications
# ─────────────────────────────────────────────────────────────────────────────
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
]

# LOCAL_APPS — every itriX app is registered here. Phase 1 ships these five;
# Phases 2–3 append their apps to this list (nothing else changes).
LOCAL_APPS = [
    "apps.core",
    "apps.authentication",
    "apps.team",
    "apps.visitors",
    "apps.review",
    # ── Phase 2 — Intelligence Core ──────────────────────────────────────────
    "apps.knowledge_core",
    "apps.ai_engine",
    "apps.routing",
    "apps.scoring",
    "apps.leads",
    "apps.result_page",
    # ── Phase 3 — Operations Layer ───────────────────────────────────────────
    "apps.emails",
    "apps.follow_up",
    "apps.nda",
    "apps.evaluations",
    "apps.pocs",
    "apps.pipeline",
    "apps.analytics",
    "apps.templates_library",
    "apps.reporting",
    "apps.notifications",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS


# ─────────────────────────────────────────────────────────────────────────────
# Middleware
# ─────────────────────────────────────────────────────────────────────────────
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    # CORS must come before CommonMiddleware so preflights are handled correctly.
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # itriX custom middleware
    "apps.core.middleware.security.SecurityHeadersMiddleware",
    "apps.core.middleware.request_logging.RequestLoggingMiddleware",
]

ROOT_URLCONF = "itrix.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "itrix.wsgi.application"
ASGI_APPLICATION = "itrix.asgi.application"


# ─────────────────────────────────────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────────────────────────────────────
# Default is sqlite (works with zero setup). When DATABASE_URL is provided it is
# parsed via dj_database_url. development.py / production.py refine this.
DATABASE_URL = env("DATABASE_URL", "")
if DATABASE_URL:
    import dj_database_url

    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL, conn_max_age=600, conn_health_checks=True
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
# Custom user model
# ─────────────────────────────────────────────────────────────────────────────
AUTH_USER_MODEL = "authentication.User"

AUTHENTICATION_BACKENDS = [
    "apps.authentication.backends.EmailBackend",
    "django.contrib.auth.backends.ModelBackend",
]


# ─────────────────────────────────────────────────────────────────────────────
# Password validation
# ─────────────────────────────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ─────────────────────────────────────────────────────────────────────────────
# Internationalisation
# ─────────────────────────────────────────────────────────────────────────────
LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True


# ─────────────────────────────────────────────────────────────────────────────
# Static & media
# ─────────────────────────────────────────────────────────────────────────────
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ─────────────────────────────────────────────────────────────────────────────
# Django REST Framework
# ─────────────────────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    # Endpoints are public by default; protected views opt in with IsDashboardUser
    # (or other permission classes). This matches the spec: Surface 1 is public,
    # Surface 2 is JWT-gated per-view.
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.AllowAny",
    ),
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardResultsPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_RENDERER_CLASSES": (
        "apps.core.renderers.ITrixJSONRenderer",
    ),
    "EXCEPTION_HANDLER": "apps.core.exceptions.itrix_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": (
        "apps.core.throttling.PublicBurstThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "public_burst": "120/min",
        "user": "1000/min",
        "review_submit": "30/min",
    },
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}


# ─────────────────────────────────────────────────────────────────────────────
# Simple JWT
# ─────────────────────────────────────────────────────────────────────────────
# Access token lives in the dashboard's httpOnly cookie; /auth/me resolves it.
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=12),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "TOKEN_OBTAIN_SERIALIZER": "apps.authentication.serializers.ITrixTokenObtainPairSerializer",
}


# ─────────────────────────────────────────────────────────────────────────────
# CORS / CSRF  (both Next.js frontends call this API directly via server proxies)
# ─────────────────────────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:3001",
)
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
    "x-itrix-client",
]

CSRF_TRUSTED_ORIGINS = env_list(
    "CSRF_TRUSTED_ORIGINS",
    "http://localhost:3000,http://localhost:3001",
)


# ─────────────────────────────────────────────────────────────────────────────
# Feature flags — let the whole system run with graceful stubs before keys exist
# ─────────────────────────────────────────────────────────────────────────────
ENABLE_AI_ENGINE = env_bool("ENABLE_AI_ENGINE", False)
ENABLE_EMAIL_DELIVERY = env_bool("ENABLE_EMAIL_DELIVERY", False)
ENABLE_CELERY = env_bool("ENABLE_CELERY", False)


# ─────────────────────────────────────────────────────────────────────────────
# External service configuration (consumed in Phases 2–3, read here once)
# ─────────────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = env("ANTHROPIC_MODEL", "claude-sonnet-4-6")
OPENAI_API_KEY = env("OPENAI_API_KEY", "")
OPENAI_EMBEDDING_MODEL = env("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
PINECONE_API_KEY = env("PINECONE_API_KEY", "")
PINECONE_INDEX = env("PINECONE_INDEX", "itrix-knowledge-core")
PINECONE_CLOUD = env("PINECONE_CLOUD", "aws")
PINECONE_REGION = env("PINECONE_REGION", "us-east-1")

RESEND_API_KEY = env("RESEND_API_KEY", "")
EMAIL_FROM = env("EMAIL_FROM", "team@itrix.ai")
EMAIL_FROM_NAME = env("EMAIL_FROM_NAME", "iTrix Assessment Team")
INTERNAL_ALERT_EMAIL = env("INTERNAL_ALERT_EMAIL", "team@itrix.ai")

REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_ALWAYS_EAGER = not ENABLE_CELERY

# Frontends (used for building absolute links in emails / result pages later)
FRONTEND_WEB_URL = env("FRONTEND_WEB_URL", "http://localhost:3000")
FRONTEND_DASHBOARD_URL = env("FRONTEND_DASHBOARD_URL", "http://localhost:3001")


# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
        "simple": {"format": "{levelname} {message}", "style": "{"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "itrix": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        # Third-party loggers that are very chatty at INFO — keep them at WARNING so the
        # ingestion output shows only our own progress lines, not their internal noise.
        "pinecone_plugin_interface": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "pinecone": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "httpx": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "httpcore": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "urllib3": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
