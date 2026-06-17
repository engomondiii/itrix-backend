"""Local development settings."""

from __future__ import annotations

from .base import *  # noqa: F401,F403
from .base import ALLOWED_HOSTS, CORS_ALLOWED_ORIGINS

DEBUG = True

# Be permissive locally so the dev server is painless.
# 'testserver' is the host DRF/Django's test client uses.
ALLOWED_HOSTS = list({*ALLOWED_HOSTS, "localhost", "127.0.0.1", "0.0.0.0", "testserver"})

# Allow any localhost port during development (helps when frontends shift ports).
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^http://localhost:\d+$",
    r"^http://127\.0\.0\.1:\d+$",
]
CORS_ALLOWED_ORIGINS = list(
    {
        *CORS_ALLOWED_ORIGINS,
        "http://localhost:3000",
        "http://localhost:3001",
    }
)

# Console email backend in dev (Resend path is gated by ENABLE_EMAIL_DELIVERY).
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Browsable API is handy in dev.
REST_FRAMEWORK = {  # noqa: F405
    **globals()["REST_FRAMEWORK"],
    "DEFAULT_RENDERER_CLASSES": (
        "apps.core.renderers.ITrixJSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ),
}
