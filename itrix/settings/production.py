"""Production settings (Railway / containerized deployments)."""

from __future__ import annotations

import os

from .base import *  # noqa: F401,F403
from .base import ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, REDIS_URL, env_bool, env_list
from .attachment_validation import validate_production_attachments
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

# ─── Attachment production contract ─────────────────────────────────────────
# Production deliberately does NOT inherit the repository-local filesystem convenience
# from base.py when attachments are enabled. The operator must choose a storage backend;
# S3-compatible storage is the Railway release path, while filesystem remains supported
# only for deployments with an explicit durable mount.
ATTACHMENT_STORAGE_BACKEND = (
    os.environ.get("ATTACHMENT_STORAGE_BACKEND", "") or ""
).strip().lower()
ATTACHMENT_BLOB_ROOT = (os.environ.get("ATTACHMENT_BLOB_ROOT", "") or "").strip()
ATTACHMENT_S3_BUCKET = (os.environ.get("ATTACHMENT_S3_BUCKET", "") or "").strip()
ATTACHMENT_S3_ENDPOINT = (os.environ.get("ATTACHMENT_S3_ENDPOINT", "") or "").strip()
ATTACHMENT_S3_REGION = (os.environ.get("ATTACHMENT_S3_REGION", "") or "").strip()
ATTACHMENT_S3_ACCESS_KEY_ID = (
    os.environ.get("ATTACHMENT_S3_ACCESS_KEY_ID", "") or ""
).strip()
ATTACHMENT_S3_SECRET_ACCESS_KEY = (
    os.environ.get("ATTACHMENT_S3_SECRET_ACCESS_KEY", "") or ""
).strip()
# Keep attachment objects in an application-owned namespace even when a bucket is shared.
# An explicitly blank value remains blank and is rejected by validation rather than being
# silently broadened to the bucket root.
ATTACHMENT_S3_PREFIX = os.environ.get("ATTACHMENT_S3_PREFIX", "attachments/").strip()
# Railway exposes an S3-compatible custom endpoint; path style avoids DNS/virtual-host
# assumptions at that endpoint. Operators may explicitly select auto/virtual when their
# provider requires it.
ATTACHMENT_S3_ADDRESSING_STYLE = os.environ.get(
    "ATTACHMENT_S3_ADDRESSING_STYLE", "path"
).strip().lower()
ATTACHMENT_SHARED_STORAGE_CONFIRMED = env_bool(
    "ATTACHMENT_SHARED_STORAGE_CONFIRMED", False
)

# The validation is import-time and structural: it verifies local scanner availability
# but never contacts S3. Provider reachability and write/read/delete integrity are checked
# by the explicit runtime validator before production enablement.
validate_production_attachments(
    enabled=ENABLE_ATTACHMENTS,
    base_dir=BASE_DIR,
    storage_backend=ATTACHMENT_STORAGE_BACKEND,
    configured_blob_root=ATTACHMENT_BLOB_ROOT,
    s3_bucket=ATTACHMENT_S3_BUCKET,
    s3_endpoint=ATTACHMENT_S3_ENDPOINT,
    s3_region=ATTACHMENT_S3_REGION,
    s3_access_key_id=ATTACHMENT_S3_ACCESS_KEY_ID,
    s3_secret_access_key=ATTACHMENT_S3_SECRET_ACCESS_KEY,
    s3_prefix=ATTACHMENT_S3_PREFIX,
    s3_addressing_style=ATTACHMENT_S3_ADDRESSING_STYLE,
    av_command=ATTACHMENT_AV_COMMAND,
    process_inline=ATTACHMENT_PROCESS_INLINE,
    shared_storage_confirmed=ATTACHMENT_SHARED_STORAGE_CONFIRMED,
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
# environment. Real delivery is still gated by ENABLE_EMAIL_DELIVERY.

# ─── Realtime / WebSocket (v4.0 Phase 2) ─────────────────────────────────────
# The `ws` Procfile process runs Daphne against itrix.asgi:application. In production
# the Redis channel layer is used when ENABLE_REALTIME is on (base.py wires this from
# REDIS_URL). We additionally pin the set of origins allowed to open a WebSocket so a
# cross-site page cannot hijack a client's socket.
ALLOWED_WS_ORIGINS = env_list("ALLOWED_WS_ORIGINS", ",".join(CSRF_TRUSTED_ORIGINS))

# channels_redis honours a TLS rediss:// URL automatically; nothing else to configure
# here — CHANNEL_LAYERS is already set in base.py from REDIS_URL.
