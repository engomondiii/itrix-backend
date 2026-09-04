"""Browser binding for the public structured-review flow.

The BFF forwards the anonymous ``itrix_visitor_session`` value in ``X-Itrix-Session``.
Only a SHA-256 digest is persisted on ``ReviewSession``.  A session created before this
control existed (empty digest) remains usable for backwards-compatible internal/tests,
but once a digest exists every public review endpoint must present the same binding.
"""
from __future__ import annotations

import hashlib
import hmac

HEADER = "HTTP_X_ITRIX_SESSION"
COOKIE = "itrix_visitor_session"


def raw_from_request(request) -> str:
    return (
        (request.META.get(HEADER, "") or "").strip()
        or (request.COOKIES.get(COOKIE, "") or "").strip()
    )[:64]


def digest(raw: str) -> str:
    return hashlib.sha256(f"review:{raw or ''}".encode("utf-8")).hexdigest() if raw else ""


def bind(session, request) -> None:
    raw = raw_from_request(request)
    if raw and not getattr(session, "access_binding_hash", ""):
        session.access_binding_hash = digest(raw)
        session.save(update_fields=["access_binding_hash", "updated_at"])


def matches(session, request) -> bool:
    expected = str(getattr(session, "access_binding_hash", "") or "")
    if not expected:
        # Public review-session UUIDs are identifiers, not credentials. A legacy or
        # malformed session without a browser binding must fail closed.
        return False
    supplied = digest(raw_from_request(request))
    return bool(supplied) and hmac.compare_digest(expected, supplied)
