"""
Anonymous-plane rate limiting and cost ceilings (Backend v6.0 §7.2, Architecture §14.1).

The public zone previously mounted no chat affordance. In v2.6 it hosts the PRIMARY
conversation — which means unauthenticated principals can now trigger model generation.
That is the largest new abuse surface in the release, and it is governed here.

Four controls:

    connect        per-session and per-IP WebSocket connection ceiling
    turn           per-session and per-IP turn-submission ceiling
    upload         per-session attachment ceiling (enforced with Phase 2)
    cost           per-session generation-cost ceiling, with automatic DOWNGRADE to
                   non-streaming rather than refusal

── THE TONE RULE ────────────────────────────────────────────────────────────
When a limit is hit the visitor gets a DETERMINISTIC, NON-PUNITIVE message. A person
describing a real compute bottleneck who happens to type quickly is not an attacker, and
the copy must never imply they are. Degrade the service, keep the conversation.

── WHY DOWNGRADE RATHER THAN REFUSE ─────────────────────────────────────────
Under load the system drops to non-streaming responses (§14.1). The conversation still
works; it just does not stream. Refusing outright would break the one promise the
surface makes — that the visitor can describe their problem and be heard.

Counters live in Django's cache. With Redis configured they are shared across processes;
with LocMem they are per-process, which still bounds a single worker. The cache is a
rate limiter, not a ledger: losing a counter fails OPEN by design, because a dropped
Redis connection must not lock every visitor out of the front door.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger("itrix")

# Cache key prefixes.
_PREFIX_CONNECT = "itrix:rl:conn"
_PREFIX_TURN = "itrix:rl:turn"
_PREFIX_UPLOAD = "itrix:rl:upload"
_PREFIX_COST = "itrix:rl:cost"

WINDOW_SECONDS = 3600


@dataclass(frozen=True)
class LimitDecision:
    """The outcome of one limit check."""

    allowed: bool
    reason: str = ""
    message: str = ""
    # True when the caller should serve a NON-STREAMING response instead of refusing.
    downgrade: bool = False
    retry_after_seconds: int | None = None

    @property
    def blocked(self) -> bool:
        return not self.allowed and not self.downgrade


def _limit(name: str, default: int) -> int:
    return int(getattr(settings, name, default))


def anon_turns_per_hour() -> int:
    return _limit("ANON_TURNS_PER_HOUR", 60)


def anon_connects_per_hour() -> int:
    return _limit("ANON_CONNECTS_PER_HOUR", 120)


def max_attachments_per_session() -> int:
    return _limit("MAX_ATTACHMENTS_PER_SESSION", 200)


def generation_cost_ceiling() -> int:
    """
    Per-session generation-cost ceiling. ``0`` (the default when unset) means NO ceiling.

    Expressed in abstract cost units so the operator can tune it per environment without
    this module knowing anything about provider pricing.
    """
    raw = getattr(settings, "ANON_GENERATION_COST_CEILING", "") or 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _bump(prefix: str, key: str, *, window: int = WINDOW_SECONDS, amount: int = 1) -> int:
    """
    Increment a windowed counter and return the new value.

    Fails OPEN (returns 0) if the cache is unavailable — a broken Redis must degrade
    rate limiting, never the front door.
    """
    if not key:
        return 0
    cache_key = f"{prefix}:{key}"
    try:
        added = cache.add(cache_key, amount, timeout=window)
        if added:
            return amount
        return int(cache.incr(cache_key, amount))
    except Exception:  # noqa: BLE001
        logger.debug("rate-limit cache unavailable for %s; failing open", cache_key)
        return 0


def _peek(prefix: str, key: str) -> int:
    if not key:
        return 0
    try:
        return int(cache.get(f"{prefix}:{key}") or 0)
    except Exception:  # noqa: BLE001
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# The checks
# ─────────────────────────────────────────────────────────────────────────────
CONNECT_MESSAGE = (
    "This conversation has reconnected several times in a short window. "
    "Give it a moment and it will pick up exactly where you left off."
)
TURN_MESSAGE = (
    "You are sending messages faster than we can review them properly. "
    "Everything you have written is saved — try again shortly."
)
UPLOAD_MESSAGE = (
    "That is more files than we can accept in one session. "
    "You can send the message without them, or remove a few and try again."
)
COST_MESSAGE = (
    "We are preparing this response without live streaming so it stays quick. "
    "The answer will appear in one piece rather than word by word."
)


def check_connect(*, session_id: str, ip: str = "") -> LimitDecision:
    """Ceiling on WebSocket connections per session and per IP."""
    ceiling = anon_connects_per_hour()
    session_count = _bump(_PREFIX_CONNECT, session_id)
    ip_count = _bump(_PREFIX_CONNECT, f"ip:{ip}") if ip else 0

    if (session_count and session_count > ceiling) or (ip_count and ip_count > ceiling * 4):
        return LimitDecision(
            allowed=False,
            reason="connect_rate_limited",
            message=CONNECT_MESSAGE,
            retry_after_seconds=60,
        )
    return LimitDecision(allowed=True)


def check_turn(*, session_id: str, ip: str = "") -> LimitDecision:
    """Ceiling on turn submissions per session and per IP."""
    ceiling = anon_turns_per_hour()
    session_count = _bump(_PREFIX_TURN, session_id)
    ip_count = _bump(_PREFIX_TURN, f"ip:{ip}") if ip else 0

    if (session_count and session_count > ceiling) or (ip_count and ip_count > ceiling * 4):
        return LimitDecision(
            allowed=False,
            reason="turn_rate_limited",
            message=TURN_MESSAGE,
            retry_after_seconds=60,
        )
    return LimitDecision(allowed=True)


def check_upload(*, session_id: str, count: int = 1) -> LimitDecision:
    """Session-level attachment ceiling. An ABUSE ceiling, not a product limit."""
    ceiling = max_attachments_per_session()
    total = _bump(_PREFIX_UPLOAD, session_id, amount=max(1, count))
    if total and total > ceiling:
        return LimitDecision(
            allowed=False,
            reason="upload_ceiling",
            message=UPLOAD_MESSAGE,
        )
    return LimitDecision(allowed=True)


def check_generation_cost(*, session_id: str, units: int = 1) -> LimitDecision:
    """
    Per-session generation-cost ceiling.

    Returns ``downgrade=True`` rather than blocking: over the ceiling the turn is served
    WITHOUT streaming. The conversation continues — only the presentation changes.
    """
    ceiling = generation_cost_ceiling()
    if ceiling <= 0:
        return LimitDecision(allowed=True)

    total = _bump(_PREFIX_COST, session_id, amount=max(1, units))
    if total and total > ceiling:
        return LimitDecision(
            allowed=False,
            downgrade=True,
            reason="generation_cost_ceiling",
            message=COST_MESSAGE,
        )
    return LimitDecision(allowed=True)


def usage_snapshot(session_id: str) -> dict:
    """Current counters for a session — internal telemetry for the cockpit."""
    return {
        "connects": _peek(_PREFIX_CONNECT, session_id),
        "turns": _peek(_PREFIX_TURN, session_id),
        "uploads": _peek(_PREFIX_UPLOAD, session_id),
        "cost_units": _peek(_PREFIX_COST, session_id),
        "limits": {
            "connects_per_hour": anon_connects_per_hour(),
            "turns_per_hour": anon_turns_per_hour(),
            "attachments_per_session": max_attachments_per_session(),
            "generation_cost_ceiling": generation_cost_ceiling(),
        },
    }


def reset(session_id: str) -> None:
    """Clear a session's counters (tests + operator action)."""
    for prefix in (_PREFIX_CONNECT, _PREFIX_TURN, _PREFIX_UPLOAD, _PREFIX_COST):
        try:
            cache.delete(f"{prefix}:{session_id}")
        except Exception:  # noqa: BLE001
            pass
