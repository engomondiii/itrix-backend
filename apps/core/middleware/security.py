"""
Security headers middleware.

Adds a small set of defensive response headers on top of Django's SecurityMiddleware.
These mirror the headers the Next.js frontends already set on their side, so the API
responses carry a consistent posture even when hit directly.
"""

from __future__ import annotations

from django.conf import settings


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("X-Content-Type-Options", "nosniff")
        response.setdefault("X-Frame-Options", "DENY")
        response.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=()",
        )
        # Advertise the API; harmless and useful for debugging integration.
        response.setdefault("X-ITrix-API", "v1")
        if not settings.DEBUG:
            response.setdefault(
                "Cross-Origin-Opener-Policy", "same-origin"
            )
        return response
