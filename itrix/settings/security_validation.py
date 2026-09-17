"""Production-only cryptographic configuration validation.

Development keeps the repository's explicit local defaults. Production must never
silently inherit them: both JWT planes use symmetric signing keys, so an absent or
predictable value is a startup failure rather than a warning.
"""

from __future__ import annotations

import hmac

from django.core.exceptions import ImproperlyConfigured

_MIN_SIGNING_KEY_LENGTH = 32
_KNOWN_INSECURE_VALUES = {
    "dev-insecure-change-me",
    "change-me",
    "changeme",
    "insecure",
    "secret",
    "test-secret",
    "test-secret-key",
    "test-key",
    "django-insecure",
}


def _require_strong_key(name: str, value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        raise ImproperlyConfigured(f"{name} is required in production.")
    lowered = raw.lower()
    if lowered in _KNOWN_INSECURE_VALUES or lowered.startswith("django-insecure-"):
        raise ImproperlyConfigured(f"{name} uses a known development/test value.")
    if len(raw) < _MIN_SIGNING_KEY_LENGTH:
        raise ImproperlyConfigured(
            f"{name} must be at least {_MIN_SIGNING_KEY_LENGTH} characters in production."
        )
    # Reject obviously repeated/predictable placeholders without attempting to invent a
    # general password-strength meter for machine-generated secrets.
    if len(set(raw)) < 8:
        raise ImproperlyConfigured(f"{name} is trivially weak.")
    return raw


def validate_production_signing_keys(
    *, secret_key: str | None, client_jwt_signing_key: str | None
) -> tuple[str, str]:
    """Validate and return the independent production signing keys.

    The client and team planes intentionally have distinct audiences. Production also
    gives them distinct keys so compromise or accidental disclosure of one signing
    capability does not automatically grant the other plane.
    """

    team_key = _require_strong_key("SECRET_KEY", secret_key)
    client_key = _require_strong_key("CLIENT_JWT_SIGNING_KEY", client_jwt_signing_key)
    if hmac.compare_digest(team_key, client_key):
        raise ImproperlyConfigured(
            "CLIENT_JWT_SIGNING_KEY must be independent from SECRET_KEY in production."
        )
    return team_key, client_key
