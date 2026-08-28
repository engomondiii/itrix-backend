"""Safe request correlation and operational logging.

One metadata-only line per request. Conversation bodies, email addresses, tokens,
query strings, attachment contents and arbitrary URL values are never logged.
"""
from __future__ import annotations

import logging
import re
import time
import uuid

logger = logging.getLogger("itrix")
_SKIP_PREFIXES = ("/healthz", "/static", "/media", "/favicon")
_CORRELATION = re.compile(r"^[A-Za-z0-9._-]{8,128}$")


def _correlation_id(request) -> str:
    incoming = (request.META.get("HTTP_X_REQUEST_ID", "") or "").strip()
    if _CORRELATION.fullmatch(incoming):
        return incoming
    return uuid.uuid4().hex


def _safe_route(request) -> str:
    """Use Django's route template, never a concrete URL that may contain a token."""
    match = getattr(request, "resolver_match", None)
    route = getattr(match, "route", "") if match is not None else ""
    if route:
        return "/" + str(route).lstrip("/")
    # Pre-resolution/error fallback: only the first static-looking segment, never query/ids.
    parts = [p for p in (request.path or "").split("/") if p]
    return f"/{parts[0]}/…" if parts else "/"


def _actor_plane(request) -> str:
    user = getattr(request, "user", None)
    if getattr(user, "is_authenticated", False):
        # No id/email/organisation. Plane is useful operational metadata; identity is not.
        module = user.__class__.__module__
        return "client" if ".clients." in module else "team"
    return "anonymous"


class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.correlation_id = _correlation_id(request)
        path = request.path or ""
        if any(path.startswith(p) for p in _SKIP_PREFIXES):
            response = self.get_response(request)
            response["X-Request-ID"] = request.correlation_id
            return response

        start = time.perf_counter()
        response = self.get_response(request)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        response["X-Request-ID"] = request.correlation_id

        logger.info(
            "request.complete request_id=%s method=%s route=%s status=%s duration_ms=%.1f plane=%s",
            request.correlation_id,
            request.method,
            _safe_route(request),
            getattr(response, "status_code", "?"),
            elapsed_ms,
            _actor_plane(request),
        )
        return response
