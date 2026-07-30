"""
AUTHENTICATION RATE LIMITING (Backend v7.2 §15.3 property 4).

Two throttles, per IP and per address, on registration, sign-in, reset requests,
confirmation resends and invitation-code lookups.

── IT SURFACES AS A STATED WAIT, NOT A SILENT FAILURE ──────────────────────
DRF returns 429 with `Retry-After` from `wait()`, and the surface renders "try again in N
minutes". A form that quietly stops working teaches people to retry harder, which is the
opposite of the intent — and Phase 4 of Surface 1 found the other half of that bug: the
login proxy had no 429 branch, so a working security control was reported as `502 login
429` and read as an outage.

── THE PER-ADDRESS KEY IS DELIBERATELY LOSSY ───────────────────────────────
It hashes the lower-cased address. Storing the address itself as a cache key would put
customer email addresses in a cache nobody audits, and the throttle only needs sameness.

── AND IT IS SWITCHABLE, FOR THE TEST SUITE ONLY ───────────────────────────
`AUTH_RATE_LIMIT_ENABLED` defaults TRUE. `tests/conftest.py`'s existing
`_disable_throttling` fixture turns it off alongside the DRF defaults, so a test that posts
twice does not trip a limit — and `test_auth_rate_limit.py` turns it back on to prove the
control works.
"""

from __future__ import annotations

import hashlib

from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle


class _AuthThrottle(SimpleRateThrottle):
    """Reads its rate straight from settings rather than from DEFAULT_THROTTLE_RATES."""

    setting_name = ""
    default_rate = "20/hour"

    def __init__(self):  # noqa: D107 - SimpleRateThrottle parses the rate in __init__
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)

    def get_rate(self):
        return str(getattr(settings, self.setting_name, None) or self.default_rate)

    def allow_request(self, request, view):
        if not bool(getattr(settings, "AUTH_RATE_LIMIT_ENABLED", True)):
            return True
        return super().allow_request(request, view)


class AuthIPThrottle(_AuthThrottle):
    scope = "auth_ip"
    setting_name = "AUTH_RATE_LIMIT_PER_IP"
    default_rate = "20/hour"

    def get_cache_key(self, request, view):
        return f"throttle_auth_ip_{self.get_ident(request)}"


class AuthAddressThrottle(_AuthThrottle):
    scope = "auth_address"
    setting_name = "AUTH_RATE_LIMIT_PER_ADDRESS"
    default_rate = "5/hour"

    def get_cache_key(self, request, view):
        raw = request.data.get("email") if hasattr(request, "data") else None
        address = (raw or "").strip().lower()
        if not address:
            # Nothing to key on. Fall through to the IP throttle rather than sharing one
            # bucket across every anonymous caller, which would make one person's typo
            # everybody's outage.
            return None
        digest = hashlib.sha256(address.encode("utf-8")).hexdigest()[:32]
        return f"throttle_auth_addr_{digest}"


AUTH_THROTTLES = [AuthIPThrottle, AuthAddressThrottle]
