"""
Throttling.

Public Surface 1 endpoints (visitor sessions, review prompt/qualify, lead capture)
are unauthenticated and abuse-prone, so they get an anon burst limit. The review
submission flow has its own tighter scope so a single visitor can't hammer the
(soon-to-be) AI generation path.

Rates are configured in ``REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']``.
"""

from __future__ import annotations

from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle


class PublicBurstThrottle(SimpleRateThrottle):
    """Per-IP burst limit for anonymous public endpoints."""

    scope = "public_burst"

    def get_cache_key(self, request, view):
        # Only throttle anonymous traffic; authenticated team users are covered by
        # the UserRateThrottle and shouldn't be limited by the public burst.
        if request.user and request.user.is_authenticated:
            return None
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class ReviewSubmitThrottle(ScopedRateThrottle):
    """
    Scoped throttle for the review submission / qualification path.

    Views set ``throttle_scope = 'review_submit'`` to activate the
    ``30/min`` rate from settings.
    """

    scope_attr = "throttle_scope"
