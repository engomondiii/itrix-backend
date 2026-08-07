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
    # Daphne must load before staticfiles so its runserver command takes over (Channels).
    "daphne",
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
    "channels",
]

# LOCAL_APPS — every itriX app is registered here. Phase 1 ships these five;
# Phases 2–3 append their apps to this list (nothing else changes).
LOCAL_APPS = [
    "apps.core",
    "apps.authentication",
    "apps.team",
    "apps.visitors",
    "apps.review",
    # ── Phase 1 (v4.0) — Identity, Journey & Agent Runtime ──────────────────
    "apps.journey",
    "apps.clients",
    "apps.agents",
    # ── Phase 1 (v6.0) — target-account persona registry (INTERNAL-ONLY) ────
    "apps.personas",
    # ── Phase 2 (v6.0) — State 10 domain + the any-format upload subsystem ──
    "apps.customer_success",
    "apps.attachments",
    # ── Phase 2 (v4.0) — Conversation & Realtime ────────────────────────────
    "apps.conversations",
    "apps.realtime",
    # ── Phase 3 (v4.0) — Governance fabric ──────────────────────────────────
    "apps.governance",
    # ── Phase 3 (v7.1) — the legal instruments and the assent record ─────────
    # Its own app because an assent record is EVIDENCE and has to outlive the account: a
    # dispute about what someone agreed to does not become moot because they closed their
    # workspace. The FK is SET_NULL for the same reason.
    "apps.legal",
    # ── Phase 1 (v7.1) — cockpit ROW-LEVEL resources ─────────────────────────
    # No models and no migrations, deliberately: a cockpit resource that owned data would
    # be a second source of truth for something another app already owns. It exists as an
    # app so the naming rule is structural — aggregates under analytics/, rows under
    # cockpit/ — and a future developer adding a distribution here has to notice they are
    # in the wrong place.
    "apps.cockpit",
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
    "apps.settings",
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
    # Two coexisting JWT audiences (v4.0): the team plane is explicitly "team";
    # the client plane ("client") is issued + verified by apps.clients.tokens.
    "AUDIENCE": "team",
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

# ── v4.0 capability flags (all default False so the shipped funnel is untouched) ──
ENABLE_AGENTS = env_bool("ENABLE_AGENTS", False)
ENABLE_CLIENT_PORTAL = env_bool("ENABLE_CLIENT_PORTAL", False)
ENABLE_REALTIME = env_bool("ENABLE_REALTIME", False)

# ─────────────────────────────────────────────────────────────────────────────
# v6.0 capability flags — ALL DEFAULT FALSE
# ─────────────────────────────────────────────────────────────────────────────
# With every flag off the backend behaves EXACTLY like the shipped build, except for the
# four security corrections, which are UNCONDITIONAL BY DESIGN. They are corrections,
# not features — a flag that can turn a security fix back off is not a fix.
#
# Ordering rule (Architecture v2.6 Appendix B.1): a FRONTEND flag may only be enabled
# once its backend counterpart is on. Enabling NEXT_PUBLIC_ENABLE_ATTACHMENTS against a
# backend without ENABLE_ATTACHMENTS presents an attach control that cannot succeed,
# which is worse than not offering it.
ENABLE_TEN_STATE_JOURNEY = env_bool("ENABLE_TEN_STATE_JOURNEY", False)
ENABLE_CONVERSATION_SURFACE = env_bool("ENABLE_CONVERSATION_SURFACE", False)
ENABLE_ANONYMOUS_STREAMING = env_bool("ENABLE_ANONYMOUS_STREAMING", False)
# Phase 2 flags — declared here so settings are complete and a deploy cannot half-know
# about them. The subsystems themselves land in Phase 2.
ENABLE_ATTACHMENTS = env_bool("ENABLE_ATTACHMENTS", False)
ENABLE_ADAPTIVE_QUESTIONS = env_bool("ENABLE_ADAPTIVE_QUESTIONS", False)
ENABLE_CUSTOMER_SUCCESS = env_bool("ENABLE_CUSTOMER_SUCCESS", False)
CUSTOMER_CONTRACT_TIER_ENABLED = env_bool("CUSTOMER_CONTRACT_TIER_ENABLED", False)
ENABLE_CUSTOMER_FIRST_NBA = env_bool("ENABLE_CUSTOMER_FIRST_NBA", False)

# ─────────────────────────────────────────────────────────────────────────────
# v6.0 conversation spine limits
# ─────────────────────────────────────────────────────────────────────────────
# THERE IS NO USER-FACING CHARACTER LIMIT (R28). MAX_MESSAGE_CHARS is a SERVER SAFETY
# CAP that returns a specific, recoverable 413. Long threads are handled by the context
# budget, never by refusing the visitor's problem.
MAX_MESSAGE_CHARS = int(env("MAX_MESSAGE_CHARS", "100000"))
CONTEXT_BUDGET_CHARS = int(env("CONTEXT_BUDGET_CHARS", "120000"))

# Anonymous thread retention. A thread that is never claimed expires on its own.
ANON_THREAD_RETENTION_DAYS = int(env("ANON_THREAD_RETENTION_DAYS", "90"))

# Anonymous-plane abuse controls. Ceilings, not product limits — the message shown when
# one is hit is deterministic and non-punitive.
ANON_TURNS_PER_HOUR = int(env("ANON_TURNS_PER_HOUR", "60"))
ANON_CONNECTS_PER_HOUR = int(env("ANON_CONNECTS_PER_HOUR", "120"))
# Blank means NO ceiling. Over the ceiling a turn DOWNGRADES to non-streaming rather
# than being refused: the conversation still works, it just does not stream.
ANON_GENERATION_COST_CEILING = env("ANON_GENERATION_COST_CEILING", "")

# Phase 2 attachment policy — declared now so the policy table has one home.
MAX_ATTACHMENT_BYTES = int(env("MAX_ATTACHMENT_BYTES", "104857600"))
MAX_ATTACHMENT_BYTES_PER_TURN = int(env("MAX_ATTACHMENT_BYTES_PER_TURN", "524288000"))
MAX_ATTACHMENTS_PER_SESSION = int(env("MAX_ATTACHMENTS_PER_SESSION", "200"))
PRE_NDA_ATTACHMENT_RETENTION_DAYS = int(env("PRE_NDA_ATTACHMENT_RETENTION_DAYS", "30"))
# Raised 3 -> 4 alongside coverage.REQUIRED_BY_STATE going from three dimensions to
# five. At three, five required dimensions would almost always have closed the loop on
# budget exhaustion rather than on coverage — the same thin diagnosis, reached a
# different way. Still a hard cap, and still what protects a visitor who does not want
# to answer. Overridable per environment.
QUESTION_BUDGET_PER_STATE = int(env("QUESTION_BUDGET_PER_STATE", "4"))

# ─────────────────────────────────────────────────────────────────────────────
# Streaming governance
# ─────────────────────────────────────────────────────────────────────────────
# The token-level guard defaults ON. Turning it off means streaming unguarded text to
# unidentified visitors, so it exists as a switch only for controlled testing.
STREAM_GUARD_ENABLED = env_bool("STREAM_GUARD_ENABLED", True)

# Support SLA badge shown from State 7 (the first PAID rung) onward.
SUPPORT_SLA_DEFAULT_HOURS = int(env("SUPPORT_SLA_DEFAULT_HOURS", "4"))

# ─────────────────────────────────────────────────────────────────────────────
# v6.0 Phase 2 — attachments
# ─────────────────────────────────────────────────────────────────────────────
# Blobs live OUTSIDE the web root. Defaulting to MEDIA_ROOT would make every upload
# publicly fetchable the moment somebody enabled media serving.
ATTACHMENT_BLOB_ROOT = env("ATTACHMENT_BLOB_ROOT", str(BASE_DIR / "private_blobs" / "attachments"))
# Optional external scanner, e.g. "clamdscan --no-summary". When unset the built-in
# type-sniffing and archive-bomb checks run, and the engine is recorded honestly as
# "builtin" so nobody reads a clean verdict as more than it is.
ATTACHMENT_AV_COMMAND = env("ATTACHMENT_AV_COMMAND", "")
# Extraction sandbox ceilings.
ATTACHMENT_EXTRACTION_TIMEOUT_SECONDS = int(env("ATTACHMENT_EXTRACTION_TIMEOUT_SECONDS", "30"))
ATTACHMENT_EXTRACTION_MEMORY_MB = int(env("ATTACHMENT_EXTRACTION_MEMORY_MB", "512"))
ATTACHMENT_MAX_EXTRACTED_CHARS = int(env("ATTACHMENT_MAX_EXTRACTED_CHARS", "400000"))
ATTACHMENT_RETENTION_DAYS = int(env("ATTACHMENT_RETENTION_DAYS", "365"))


# ─────────────────────────────────────────────────────────────────────────────
# Legal instruments (v7.1 Phase 3 — Architecture v2.8 §19.10)
# ─────────────────────────────────────────────────────────────────────────────
# ── THE VERSIONS LIVE HERE, NOT IN A MODULE ─────────────────────────────────
# A version is a DEPLOYMENT FACT: the running build serves a particular text, and the assent
# record has to name the version that build showed. Hard-coding it in Python means a hotfix
# to the wording ships without the version moving, and every assent recorded afterwards
# points at a document nobody read.
#
# THESE MUST MATCH itrix-web/src/lib/content/legalCopy.ts. When they do not,
# `GET legal/instruments/` and the frontend disagree, `useLegalAssent` warns in development,
# and `audit_assent` reports it — because the mismatch means every assent being recorded is
# attached to a version the visitor did not read.
LEGAL_TERMS_VERSION = env("LEGAL_TERMS_VERSION", "1.1")
LEGAL_TERMS_EFFECTIVE = env("LEGAL_TERMS_EFFECTIVE", "")
LEGAL_PRIVACY_VERSION = env("LEGAL_PRIVACY_VERSION", "1.1")
LEGAL_PRIVACY_EFFECTIVE = env("LEGAL_PRIVACY_EFFECTIVE", "")
LEGAL_SECURITY_VERSION = env("LEGAL_SECURITY_VERSION", "1.1")
LEGAL_SECURITY_EFFECTIVE = env("LEGAL_SECURITY_EFFECTIVE", "")
LEGAL_DISCLOSURE_VERSION = env("LEGAL_DISCLOSURE_VERSION", "1.1")
LEGAL_DISCLOSURE_EFFECTIVE = env("LEGAL_DISCLOSURE_EFFECTIVE", "")

# Whether counsel has signed the instruments off.
#
# DEFAULTS FALSE, and the routes still answer with it false — a visitor must always be able to
# read what governs their use. What changes is that the payload says `published: false`, and
# itrix-web renders a draft banner and a noindex. An unreviewed Terms of Service presented as
# authoritative is worse than a delayed one.
LEGAL_PUBLISHED = env("LEGAL_PUBLISHED", "False").lower() == "true"

# ─────────────────────────────────────────────────────────────────────────────
# v6.0 Phase 3
# ─────────────────────────────────────────────────────────────────────────────
# The customer-first precedence rule. With this OFF the highest-weighted candidate wins
# (the pre-Phase-3 behaviour), so the flag is genuinely reversible. With it ON, support
# and outcome actions provably outrank expansion on BOTH surfaces.
ENABLE_CUSTOMER_FIRST_NBA = env_bool("ENABLE_CUSTOMER_FIRST_NBA", False)


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

# ─────────────────────────────────────────────────────────────────────────────
# OUTBOUND EMAIL
#
# ── TWO PROVIDERS, ONE CHOKE-POINT ───────────────────────────────────────────
# `apps.emails.services.email_sender.send_email` is the only place outbound mail is
# created (that is what makes the R66 confirmation gate a single rule rather than
# something every builder has to remember). It can now deliver through either:
#
#   smtp    Django's own mail backend — Gmail / Google Workspace, or any SMTP host
#   resend  the Resend HTTP API, as before
#
# EMAIL_PROVIDER selects. "auto" (the default) means: use SMTP when a host user is
# configured, otherwise Resend when an API key is configured, otherwise nothing is
# deliverable and every send is logged as stubbed.
#
# ── THE ENVELOPE SENDER IS DERIVED, NOT ASSUMED ──────────────────────────────
# Gmail refuses to send with a From address that is neither the authenticated
# mailbox nor one of its verified aliases. Leaving EMAIL_FROM pointing at a
# different domain while authenticating as another mailbox is the single most
# common way this configuration fails, and it fails at send time with an SMTP
# error rather than at boot. So when the provider is SMTP and EMAIL_FROM has not
# been set explicitly, the authenticated mailbox becomes the sender.
# ─────────────────────────────────────────────────────────────────────────────
RESEND_API_KEY = env("RESEND_API_KEY", "")

EMAIL_HOST = env("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(env("EMAIL_PORT", "587") or 587)
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_HOST_USER = (env("EMAIL_HOST_USER", "gpslab@iwl.kr") or "").strip()

# Google shows app passwords in four spaced groups ("abcd efgh ijkl mnop") and people
# paste them that way. SMTP AUTH would fail on the spaces, so they are stripped here
# rather than left as a support call.
#
# NO DEFAULT VALUE. A credential with a fallback in source control is a credential in
# every clone, branch and CI log of this repository — and rotating it then means
# editing code rather than an environment variable. Set EMAIL_HOST_PASSWORD in the
# environment; when it is absent nothing is deliverable and every send is logged.
EMAIL_HOST_PASSWORD = "".join((env("EMAIL_HOST_PASSWORD", "") or "").split())
EMAIL_TIMEOUT = int(env("EMAIL_TIMEOUT", "20") or 20)

EMAIL_PROVIDER = (env("EMAIL_PROVIDER", "auto") or "auto").strip().lower()
if EMAIL_PROVIDER not in {"auto", "smtp", "resend", "none"}:
    EMAIL_PROVIDER = "auto"
if EMAIL_PROVIDER == "auto":
    if EMAIL_HOST_USER and EMAIL_HOST_PASSWORD:
        EMAIL_PROVIDER = "smtp"
    elif RESEND_API_KEY:
        EMAIL_PROVIDER = "resend"
    else:
        EMAIL_PROVIDER = "none"

EMAIL_FROM_NAME = env("EMAIL_FROM_NAME", "iTrix Assessment Team")

# ── THE SENDER IS DECIDED BY THE PROVIDER, NOT BY PREFERENCE ────────────────
# Under SMTP the authenticated mailbox WINS over EMAIL_FROM, and that is not a
# stylistic choice. Gmail and Google Workspace refuse a From address the credential
# does not own (553 / SMTPSenderRefused); the message is rejected at send time, in a
# background task, long after the visitor has been told to check their email.
#
# This deployment is exactly that trap: EMAIL_FROM is set to a different domain from
# EMAIL_HOST_USER. Honouring it would mean every confirmation link failing to send
# while the configuration looked deliberate. So EMAIL_FROM is ignored here and the
# reason is logged, rather than being obeyed into a guaranteed failure.
#
# EMAIL_FROM still binds for Resend, which verifies DOMAINS rather than mailboxes and
# so can legitimately send as an address that is not a real inbox.
_email_from_env = (env("EMAIL_FROM", "") or "").strip()
EMAIL_FROM_IGNORED = ""

if EMAIL_PROVIDER == "smtp" and EMAIL_HOST_USER:
    EMAIL_FROM = EMAIL_HOST_USER
    if _email_from_env and _email_from_env.lower() != EMAIL_HOST_USER.lower():
        # Surfaced by apps.emails.EmailsConfig.ready() so it appears once at boot.
        EMAIL_FROM_IGNORED = _email_from_env
elif _email_from_env:
    EMAIL_FROM = _email_from_env
else:
    EMAIL_FROM = "team@itrix.ai"

# Django's own default, used by anything that calls send_mail() directly. Kept in step
# with EMAIL_FROM so there is one sender identity rather than two.
DEFAULT_FROM_EMAIL = f"{EMAIL_FROM_NAME} <{EMAIL_FROM}>" if EMAIL_FROM_NAME else EMAIL_FROM
SERVER_EMAIL = EMAIL_FROM

# The Django transport. `development.py` narrows this to the console when nothing is
# configured, so a developer with no credentials still sees the mail body.
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")

INTERNAL_ALERT_EMAIL = env("INTERNAL_ALERT_EMAIL", "team@itrix.ai")

REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_ALWAYS_EAGER = not ENABLE_CELERY

# ── Channels / realtime transport (v4.0 Phase 2) ─────────────────────────────
# When ENABLE_REALTIME is on we use the Redis channel layer (reusing REDIS_URL) so
# WebSocket fan-out works across processes. Otherwise we use the in-memory layer,
# which is perfect for tests and single-process dev and requires no broker.
#
# ── WHY PUBSUB AND NOT THE CORE LAYER ────────────────────────────────────────
# This was `channels_redis.core.RedisChannelLayer` with `{"hosts": [REDIS_URL]}`
# and nothing else, and it did not survive contact with Railway.
#
# The core layer receives by BLOCKING ON BRPOP. Railway's internal network drops
# a connection that has been idle, the blocked read never returns, and the socket
# raises:
#
#     redis.exceptions.TimeoutError: Timeout reading from redis.railway.internal:6379
#       ... in channels/utils.py await_many_dispatch
#
# That traceback is the consumer's own receive loop, so the exception kills the
# consumer and the browser reconnects — which is the WSCONNECT/WSDISCONNECT
# cycling every few seconds in the production logs.
#
# It is not a cosmetic log problem. This layer is the transport for every realtime
# feature: streamed tokens, team replies reaching a visitor, live thread titles,
# the client-page reveal. A socket that dies every few seconds delivers none of
# them reliably, however correct the code above it is.
#
# `RedisPubSubChannelLayer` uses Redis pub/sub instead of long BRPOP polls. There
# is no long-lived blocking read to time out, and it is the layer channels_redis
# recommends for exactly this deployment shape.
#
# ── AND THE SETTINGS THAT KEEP IT ALIVE ──────────────────────────────────────
# `health_check_interval` makes redis-py PING an idle connection rather than
# discovering it is dead by failing a real read. `socket_keepalive` asks the OS to
# keep the TCP connection warm, which is what stops the network dropping it in the
# first place. Both are per-host config, hence the dict form rather than a bare URL.
if ENABLE_REALTIME:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.pubsub.RedisPubSubChannelLayer",
            "CONFIG": {
                "hosts": [
                    {
                        "address": REDIS_URL,
                        # PING an idle connection every 30s instead of finding out
                        # it is dead when a real read fails.
                        "health_check_interval": 30,
                        # Keep the TCP connection warm so the network has no idle
                        # window in which to drop it.
                        "socket_keepalive": True,
                        # Bounded, so a genuinely unreachable Redis fails fast and
                        # visibly rather than hanging a worker.
                        "socket_connect_timeout": 5,
                    }
                ],
                # Namespaces the pub/sub channels. Without it, another service
                # sharing this Redis instance would collide with our group names.
                "prefix": "itrix",
            },
        }
    }
else:
    CHANNEL_LAYERS = {
        "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
    }

# Frontends (used for building absolute links in emails / result pages later)
FRONTEND_WEB_URL = env("FRONTEND_WEB_URL", "http://localhost:3000")
FRONTEND_DASHBOARD_URL = env("FRONTEND_DASHBOARD_URL", "http://localhost:3001")

# ── v4.0 identity plane + agent runtime configuration ────────────────────────
# Capability tokens (journey reveals) are HMAC-signed with this secret; the client
# plane signs its own JWTs with CLIENT_JWT_SIGNING_KEY. Both fall back to SECRET_KEY
# so the project boots before the keys are provisioned.
CAPABILITY_TOKEN_SECRET = env("CAPABILITY_TOKEN_SECRET", SECRET_KEY)
CLIENT_JWT_SIGNING_KEY = env("CLIENT_JWT_SIGNING_KEY", SECRET_KEY)
# Single-use account-invite token lifetime (reveal ② → ③).
ACCOUNT_INVITE_TTL_HOURS = int(env("ACCOUNT_INVITE_TTL_HOURS", "72"))

# ─────────────────────────────────────────────────────────────────────────────
# v7.2 Phase 4 — open registration, confirmation and credentials
# ─────────────────────────────────────────────────────────────────────────────
# ENABLE_OPEN_SIGNUP DEFAULTS TRUE. It is retired as a product gate and kept as a KILL
# SWITCH (Architecture v2.9 §22.1): an unset variable now has to mean "registration is
# available", and `env_bool` already supports that by taking the default when unset.
#
# RELEASE ORDER IS NOT NEGOTIABLE (§15.9):
#   1  manage.py audit_client_emails    must come back clean
#   2  migrate clients                  adds the uniqueness constraint
#   3  ENABLE_OPEN_SIGNUP=True          only now
# Shipping this on before the constraint means accepting registrations into a schema that
# cannot keep its one-address-one-account promise.
ENABLE_OPEN_SIGNUP = env_bool("ENABLE_OPEN_SIGNUP", True)
ENABLE_PASSWORD_RESET = env_bool("ENABLE_PASSWORD_RESET", True)

# Confirmation gates three things and only three: any non-transactional email, putting an
# NDA in place, and being named on a commercial document (R66). It does NOT gate signing in,
# posting a turn, or receiving an answer. Off exists for a deployment with no working mail,
# not as a product option.
REQUIRE_EMAIL_VERIFICATION = env_bool("REQUIRE_EMAIL_VERIFICATION", True)
VERIFICATION_TOKEN_TTL_HOURS = int(env("VERIFICATION_TOKEN_TTL_HOURS", "48"))
RESET_TOKEN_TTL_MINUTES = int(env("RESET_TOKEN_TTL_MINUTES", "60"))

# ONE number, and this is the one that binds. Terms §3A, Security §3A and
# Surface 1 v8.0 §16.7 all state it too; if they ever differ, this is the truth
# (Legal Instruments v1.2 §A.3).
PASSWORD_MIN_LENGTH = int(env("PASSWORD_MIN_LENGTH", "12"))

# Server-side, per address and per IP, surfacing as a stated wait rather than a silent
# failure. AUTH_RATE_LIMIT_ENABLED exists so `tests/conftest.py` can switch it off with the
# DRF defaults; production keeps it on.
AUTH_RATE_LIMIT_ENABLED = env_bool("AUTH_RATE_LIMIT_ENABLED", True)
AUTH_RATE_LIMIT_PER_IP = env("AUTH_RATE_LIMIT_PER_IP", "20/hour")
AUTH_RATE_LIMIT_PER_ADDRESS = env("AUTH_RATE_LIMIT_PER_ADDRESS", "5/hour")

# An account opened and then never used at all — no conversation, no confirmed address, no
# sign-in — is purged after this window (Privacy v1.2 §8). One number, two places.
ABANDONED_ACCOUNT_DAYS = int(env("ABANDONED_ACCOUNT_DAYS", "180"))
# Agent output at/below this claim level auto-delivers; above it queues for human
# approval (Backend v4 §5.2 governance).
AGENT_AUTO_APPROVE_MAX_LEVEL = int(env("AGENT_AUTO_APPROVE_MAX_LEVEL", "2"))

# ── AI call hardening (v4.0.1) ───────────────────────────────────────────────
# Hard wall-clock timeout (seconds) applied to every Claude / OpenAI / Pinecone call so
# a slow or stalled provider can never tie up a web worker (Railway gunicorn kills
# workers at --timeout 120). Keep this well under that limit.
AI_CALL_TIMEOUT_SECONDS = int(env("AI_CALL_TIMEOUT_SECONDS", "20"))
# SDK-level retry cap for a single Claude call (kept small so total latency stays bounded).
AI_CALL_MAX_RETRIES = int(env("AI_CALL_MAX_RETRIES", "1"))
# Whether the internal lead summary may use Claude on the (synchronous) creation path.
# OFF by default so lead creation is instant; the deterministic summary is always safe.
LEAD_SUMMARY_USE_AI = env_bool("LEAD_SUMMARY_USE_AI", False)


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
