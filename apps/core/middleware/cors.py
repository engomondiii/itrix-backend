"""
CORS helper middleware.

The heavy lifting is done by ``corsheaders`` (configured in settings). This thin
wrapper exists for two reasons the spec calls for a dedicated module:

1. It guarantees a ``Vary: Origin`` header on every response so shared caches never
   serve one origin's CORS headers to another.
2. It provides a single, obvious place to add bespoke cross-origin rules later
   (e.g. exposing a custom response header to the dashboard) without editing the
   third-party package configuration.
"""

from __future__ import annotations

from django.utils.deprecation import MiddlewareMixin


class CorsVaryMiddleware(MiddlewareMixin):
    """Ensure responses vary on Origin (correct caching for CORS)."""

    def process_response(self, request, response):
        existing = response.get("Vary", "")
        parts = [p.strip() for p in existing.split(",") if p.strip()]
        if "Origin" not in parts:
            parts.append("Origin")
            response["Vary"] = ", ".join(parts)
        return response
