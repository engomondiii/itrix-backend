"""
Streaming-governance analytics (Backend v6.0 §Phase 3, §6.4).

    envelope downgrades · guard halts · settle replacements, per agent / state / plane

── THE INTERPRETATION RULE ──────────────────────────────────────────────────
§6.4: a rising guard-hit rate is treated as RETRIEVAL OR PROMPT DRIFT, NOT AS NOISE.

That is why this module exists at all. A halt is not a success story about the guard
working — it is a signal that a model tried to say something it should never have been
in a position to say, and the interesting question is what changed upstream.

``stream_guard_hits`` is on the §10.5 internal-only list, and ``matched_text`` in
particular is the prohibited wording itself. None of it leaves the team plane.
"""

from __future__ import annotations

import logging

from django.db.models import Count
from django.utils import timezone

logger = logging.getLogger("itrix")


def _qs(window_days: int):
    from apps.governance.models import StreamGuardHit

    since = timezone.now() - timezone.timedelta(days=window_days)
    return StreamGuardHit.objects.filter(created_at__gte=since)


def totals(*, window_days: int = 30) -> dict:
    from apps.governance.models import StreamGuardHit

    qs = _qs(window_days)
    return {
        "halts": qs.filter(kind=StreamGuardHit.Kind.HALT).count(),
        "envelopeDowngrades": qs.filter(kind=StreamGuardHit.Kind.ENVELOPE_DOWNGRADE).count(),
        "settleReplacements": qs.filter(kind=StreamGuardHit.Kind.SETTLE_REPLACEMENT).count(),
        "windowDays": window_days,
    }


def by_category(*, window_days: int = 30) -> dict:
    """
    Which rule fired.

    The most actionable breakdown: a spike in ``benchmark`` means retrieval is surfacing
    unapproved figures; a spike in ``inferred_identity`` means the prompt has drifted
    toward profiling.
    """
    rows = _qs(window_days).values("category").annotate(n=Count("id")).order_by("-n")
    return {row["category"] or "unknown": row["n"] for row in rows}


def by_agent(*, window_days: int = 30) -> dict:
    rows = _qs(window_days).values("agent_key").annotate(n=Count("id")).order_by("-n")
    return {row["agent_key"] or "unknown": row["n"] for row in rows}


def by_plane(*, window_days: int = 30) -> dict:
    """
    Halts per plane.

    The anonymous plane is the one to watch: it is the newest surface and the one where a
    halt has the widest blast radius.
    """
    rows = _qs(window_days).values("plane").annotate(n=Count("id")).order_by("-n")
    return {row["plane"] or "unknown": row["n"] for row in rows}


def by_state(*, window_days: int = 30) -> dict:
    rows = _qs(window_days).values("journey_state").annotate(n=Count("id")).order_by("-n")
    return {row["journey_state"] or "unknown": row["n"] for row in rows}


def drift_signal(*, window_days: int = 7, baseline_days: int = 28) -> dict:
    """
    Is the halt rate RISING?

    Compares the recent window against the preceding baseline. A ratio meaningfully above
    1.0 is the drift signal §6.4 describes — and it is reported as a ratio plus both raw
    counts, so a jump from 1 to 3 is not mistaken for a crisis.
    """
    from apps.governance.models import StreamGuardHit

    now = timezone.now()
    recent_start = now - timezone.timedelta(days=window_days)
    baseline_start = now - timezone.timedelta(days=baseline_days)

    recent = StreamGuardHit.objects.filter(created_at__gte=recent_start).count()
    baseline = StreamGuardHit.objects.filter(
        created_at__gte=baseline_start, created_at__lt=recent_start
    ).count()

    recent_rate = recent / max(window_days, 1)
    baseline_rate = baseline / max(baseline_days - window_days, 1)
    ratio = round(recent_rate / baseline_rate, 2) if baseline_rate else None

    return {
        "recent": recent,
        "baseline": baseline,
        "recentPerDay": round(recent_rate, 2),
        "baselinePerDay": round(baseline_rate, 2),
        "ratio": ratio,
        "rising": bool(ratio is not None and ratio > 1.5),
        "interpretation": (
            "A rising halt rate is retrieval or prompt drift, not noise. "
            "Check what changed in retrieval or the system prompt."
        ),
    }


def recent_hits(*, limit: int = 50) -> list[dict]:
    """
    Recent halts for the cockpit. TEAM PLANE ONLY.

    Includes ``matchedText`` — the prohibited wording itself. It exists so an operator can
    see what the model tried to say, and it must never appear anywhere else.
    """
    from apps.governance.models import StreamGuardHit

    return [
        {
            "id": str(hit.id),
            "kind": hit.kind,
            "category": hit.category,
            "pattern": hit.pattern,
            "matchedText": hit.matched_text,
            "agentKey": hit.agent_key,
            "plane": hit.plane,
            "threadId": hit.thread_id,
            "at": hit.created_at.isoformat(),
        }
        for hit in StreamGuardHit.objects.order_by("-created_at")[:limit]
    ]


def summary() -> dict:
    return {
        "totals": totals(),
        "byCategory": by_category(),
        "byAgent": by_agent(),
        "byPlane": by_plane(),
        "byState": by_state(),
        "drift": drift_signal(),
    }
