"""Production settings (Railway / containerized deployments)."""

from __future__ import annotations

import os

from .base import *  # noqa: F401,F403
from .base import ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, REDIS_URL, env_bool, env_list
from .security_validation import validate_production_signing_keys

DEBUG = False

# ─── Cryptographic production contract ───────────────────────────────────────
# base.py deliberately keeps a repository-known development SECRET_KEY so a fresh local
# checkout can boot. Production must never inherit that convenience. The client JWT plane
# also gets an independent mandatory key rather than silently falling back to SECRET_KEY.
# Values live only in the deployment environment; never commit them.
CLIENT_JWT_SIGNING_KEY = (os.environ.get("CLIENT_JWT_SIGNING_KEY") or "").strip()
validate_production_signing_keys(
    secret_key=SECRET_KEY,
    client_jwt_signing_key=CLIENT_JWT_SIGNING_KEY,
)

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

# Email: the transport and the provider are both resolved in base.py now, from the
# environment. This file used to pin EMAIL_BACKEND to SMTP and describe Resend as
# "preferred", which was true of an earlier deployment and misleading afterwards —
# `email_sender` reads settings.EMAIL_PROVIDER, and base.py derives it.
#
# Real delivery is still gated by ENABLE_EMAIL_DELIVERY, so a production deploy with
# credentials present but the flag off sends nothing and logs every attempt.


# ─── Realtime / WebSocket (v4.0 Phase 2) ─────────────────────────────────────
# The `ws` Procfile process runs Daphne against itrix.asgi:application. In production
# the Redis channel layer is used when ENABLE_REALTIME is on (base.py wires this from
# REDIS_URL). We additionally pin the set of origins allowed to open a WebSocket so a
# cross-site page cannot hijack a client's socket.
ALLOWED_WS_ORIGINS = env_list("ALLOWED_WS_ORIGINS", ",".join(CSRF_TRUSTED_ORIGINS))

# channels_redis honours a TLS rediss:// URL automatically; nothing else to configure
# here — CHANNEL_LAYERS is already set in base.py from REDIS_URL.
