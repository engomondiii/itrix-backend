"""
Client-JWT token helpers (audience=client).

The client plane uses its OWN JWTs, distinct from the team plane. Two guarantees keep
the planes from bleeding into each other (Backend v4 §3.1):

  * ``aud="client"`` is embedded in every client token; ``ClientJWTAuth`` rejects any
    token whose audience is not "client".
  * The tokens are signed with ``CLIENT_JWT_SIGNING_KEY`` (falls back to SECRET_KEY),
    which can differ from the team signing key.

A client is NOT a Django auth User, so we mint tokens manually (SimpleJWT's
``for_user`` assumes the auth user model). The claims carry the client id + email +
lead id + NDA state so the portal can render without an extra DB hit; the DB remains
authoritative (resolved via ``/client/me/`` in Phase 2).
"""

from __future__ import annotations

import time
import uuid

import jwt
from django.conf import settings

CLIENT_AUDIENCE = "client"
_ACCESS_TTL = 30 * 60  # 30 minutes
_REFRESH_TTL = 14 * 24 * 60 * 60  # 14 days


def _signing_key() -> str:
    return getattr(settings, "CLIENT_JWT_SIGNING_KEY", "") or settings.SECRET_KEY


def _algo() -> str:
    return settings.SIMPLE_JWT.get("ALGORITHM", "HS256")


def _encode(payload: dict) -> str:
    token = jwt.encode(payload, _signing_key(), algorithm=_algo())
    # PyJWT >= 2 returns str already; guard for older versions returning bytes.
    return token.decode("utf-8") if isinstance(token, bytes) else token


def build_tokens_for_client(client) -> dict[str, str]:
    """Return a fresh ``{access, refresh}`` pair for a client (audience=client)."""
    now = int(time.time())
    base = {
        "aud": CLIENT_AUDIENCE,
        "client_id": str(client.id),
        "lead_id": str(client.lead_id),
        "email": client.email,
        "nda_signed": bool(client.nda_signed),
        "iat": now,
        "jti": uuid.uuid4().hex,
        # Monotonic revocation boundary. Unlike JWT iat, this cannot lose precision when a
        # password change and token issue happen in the same second.
        "session_version": int(getattr(client, "session_version", 0) or 0),
    }
    access = {**base, "token_type": "access", "exp": now + _ACCESS_TTL}
    refresh = {**base, "token_type": "refresh", "exp": now + _REFRESH_TTL}
    return {"access": _encode(access), "refresh": _encode(refresh)}


def decode_client_token(token: str) -> dict:
    """
    Decode + validate a client token. Enforces ``aud="client"``. Raises
    ``jwt.PyJWTError`` subclasses on any problem (expired, bad sig, wrong audience).
    """
    return jwt.decode(
        token,
        _signing_key(),
        algorithms=[_algo()],
        audience=CLIENT_AUDIENCE,
        options={"require": ["exp", "aud"]},
    )


def token_matches_current_session(client, payload: dict) -> bool:
    """Return whether a decoded client token belongs to the client's current session generation.

    New tokens carry ``session_version``. Legacy tokens minted before the migration remain
    usable only while no session invalidation has ever occurred. Once ``password_changed_at``
    is set, a missing generation fails closed.
    """
    current = int(getattr(client, "session_version", 0) or 0)
    claimed = payload.get("session_version")
    if claimed is None:
        return current == 0 and getattr(client, "password_changed_at", None) is None
    try:
        return int(claimed) == current
    except (TypeError, ValueError):
        return False
