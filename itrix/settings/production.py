"""Production settings (Railway / containerized deployments)."""

from __future__ import annotations

import os

from .base import *  # noqa: F401,F403
from .base import ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, env_bool

DEBUG = False

# Railway provides RAILWAY_PUBLIC_DOMAIN / RAILWAY_STATIC_URL; trust them.
_railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
if _railway_domain:
    ALLOWED_HOSTS = list({*ALLOWED_HOSTS, _railway_domain})
    CSRF_TRUSTED_ORIGINS = list({*CSRF_TRUSTED_ORIGINS, f"https://{_railway_domain}"})

# If a wildcard is desired in constrained PaaS environments, allow opt-in.
if env_bool("ALLOW_ALL_HOSTS", False):
    ALLOWED_HOSTS = ["*"]

# ─── HTTPS / security hardening ──────────────────────────────────────────────
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"

# Email: real delivery is still gated by ENABLE_EMAIL_DELIVERY inside the service;
# the SMTP backend here is only the Django fallback when something calls send_mail
# directly. The Resend service path is preferred.
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
