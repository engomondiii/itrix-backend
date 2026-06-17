"""
Request logging middleware.

Logs one structured line per API request with method, path, status, and duration.
Health checks and admin/static noise are skipped. Bodies are never logged (the
review prompt and lead capture may contain PII), keeping logs safe to ship.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger("itrix")

_SKIP_PREFIXES = ("/healthz", "/static", "/media", "/favicon")


class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or ""
        if any(path.startswith(p) for p in _SKIP_PREFIXES):
            return self.get_response(request)

        start = time.perf_counter()
        response = self.get_response(request)
        elapsed_ms = (time.perf_counter() - start) * 1000.0

        user = getattr(request, "user", None)
        actor = (
            user.email
            if getattr(user, "is_authenticated", False) and getattr(user, "email", None)
            else "anon"
        )
        logger.info(
            "%s %s -> %s (%.1fms) [%s]",
            request.method,
            path,
            getattr(response, "status_code", "?"),
            elapsed_ms,
            actor,
        )
        return response
