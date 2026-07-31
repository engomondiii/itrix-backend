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

# ── Email in development ─────────────────────────────────────────────────────
# The console backend is the right default locally: a developer with no credentials
# still sees the whole message body, including the verification link, in the terminal.
#
# But it USED to be unconditional, which meant a real SMTP configuration could not be
# exercised locally at all — the one place you would want to test it before deploying.
# So it now yields when a mailbox is actually configured, and `EMAIL_BACKEND` in the
# environment still overrides both.
from .base import EMAIL_HOST_PASSWORD, EMAIL_HOST_USER, env  # noqa: E402

_explicit_backend = env("EMAIL_BACKEND", "")
if _explicit_backend:
    EMAIL_BACKEND = _explicit_backend
elif EMAIL_HOST_USER and EMAIL_HOST_PASSWORD:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Browsable API is handy in dev.
REST_FRAMEWORK = {  # noqa: F405
    **globals()["REST_FRAMEWORK"],
    "DEFAULT_RENDERER_CLASSES": (
        "apps.core.renderers.ITrixJSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ),
}
