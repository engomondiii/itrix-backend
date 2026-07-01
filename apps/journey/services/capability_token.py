"""
Capability tokens (Backend v4 §3.4 / Appendix B).

    token   = base64url(payload) + "." + base64url(HMAC_SHA256(secret, payload))
    payload = { sub, typ, state, exp, nonce, single_use }

A capability token grants REACH to a URL — never data. On every request the server:
    verify sig + exp  →  load sub  →  assert the journey permits `typ`
                      →  (if single_use) consume the nonce atomically
Data is released only when (token valid) AND (journey permits) AND (disclosure allows).

This module is pure crypto + encoding; the "journey permits" and "disclosure allows"
checks live in the views/gate. Signing uses ``CAPABILITY_TOKEN_SECRET`` (falls back to
``SECRET_KEY`` so the system boots before the key is set).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass

from django.conf import settings

# Token types (mirror RevealSurface but are the token vocabulary).
TOKEN_CLIENT_PAGE = "client_page"
TOKEN_ACCOUNT_INVITE = "account_invite"
TOKEN_PORTAL = "portal"

VALID_TYPES = {TOKEN_CLIENT_PAGE, TOKEN_ACCOUNT_INVITE, TOKEN_PORTAL}

_DEFAULT_TTL_SECONDS = 60 * 60 * 24 * 14  # 14 days


class CapabilityTokenError(Exception):
    """Raised when a token is malformed, mis-signed, expired, or wrong-typed."""


@dataclass(frozen=True)
class TokenPayload:
    sub: str
    typ: str
    state: str
    exp: int
    nonce: str
    single_use: bool

    def to_dict(self) -> dict:
        return {
            "sub": self.sub,
            "typ": self.typ,
            "state": self.state,
            "exp": self.exp,
            "nonce": self.nonce,
            "single_use": self.single_use,
        }


def _secret() -> bytes:
    raw = getattr(settings, "CAPABILITY_TOKEN_SECRET", "") or settings.SECRET_KEY
    return raw.encode("utf-8")


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _sign(payload_bytes: bytes) -> bytes:
    return hmac.new(_secret(), payload_bytes, hashlib.sha256).digest()


def mint(
    *,
    sub: str,
    typ: str,
    state: str,
    ttl_seconds: int | None = None,
    single_use: bool = False,
) -> str:
    """Create a signed capability token for subject ``sub`` and type ``typ``."""
    if typ not in VALID_TYPES:
        raise CapabilityTokenError(f"Unknown token type: {typ!r}")
    exp = int(time.time()) + int(ttl_seconds if ttl_seconds is not None else _DEFAULT_TTL_SECONDS)
    payload = TokenPayload(
        sub=str(sub),
        typ=typ,
        state=str(state),
        exp=exp,
        nonce=uuid.uuid4().hex,
        single_use=bool(single_use),
    )
    payload_bytes = json.dumps(payload.to_dict(), separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = _sign(payload_bytes)
    return f"{_b64e(payload_bytes)}.{_b64e(sig)}"


def verify(token: str, *, expected_typ: str | None = None) -> TokenPayload:
    """
    Verify signature + expiry (and optionally the type) and return the payload.

    Raises ``CapabilityTokenError`` on any problem. Does NOT check the journey or
    consume single-use nonces — the caller does that after loading the subject.
    """
    if not token or "." not in token:
        raise CapabilityTokenError("Malformed token.")
    payload_b64, sig_b64 = token.split(".", 1)
    try:
        payload_bytes = _b64d(payload_b64)
        provided_sig = _b64d(sig_b64)
    except Exception as exc:  # noqa: BLE001
        raise CapabilityTokenError("Undecodable token.") from exc

    expected_sig = _sign(payload_bytes)
    if not hmac.compare_digest(provided_sig, expected_sig):
        raise CapabilityTokenError("Bad signature.")

    try:
        data = json.loads(payload_bytes.decode("utf-8"))
        payload = TokenPayload(
            sub=str(data["sub"]),
            typ=str(data["typ"]),
            state=str(data.get("state", "")),
            exp=int(data["exp"]),
            nonce=str(data["nonce"]),
            single_use=bool(data.get("single_use", False)),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise CapabilityTokenError("Invalid payload.") from exc

    if payload.exp < int(time.time()):
        raise CapabilityTokenError("Token expired.")
    if expected_typ is not None and payload.typ != expected_typ:
        raise CapabilityTokenError(f"Wrong token type: expected {expected_typ!r}, got {payload.typ!r}.")

    return payload
