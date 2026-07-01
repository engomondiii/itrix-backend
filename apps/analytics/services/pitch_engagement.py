"""
Pitch-engagement aggregator (Backend v4 §Phase 3, §Integration).

Surface 1's pitch room fires telemetry events — pitch.opened, slide_viewed, slide_dwell,
cta_clicked, question_asked, reopened. This service aggregates exactly those into the
cockpit fields Surface 2 renders. Internal signals never leave the team plane: this is
consumed only by team-JWT cockpit + analytics endpoints.

Telemetry is read from the AgentRun audit rows for the Pitch agent plus any recorded
pitch.* events. When no telemetry exists yet (fresh lead, events not wired), it returns a
zeroed but well-shaped payload so the cockpit renders cleanly.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger("itrix")

# The canonical pitch event names (match Surface 1's emitter).
PITCH_EVENTS = ("opened", "slide_viewed", "slide_dwell", "cta_clicked", "question_asked", "reopened")


def _empty_engagement() -> dict:
    return {
        "opened": 0,
        "slidesViewed": 0,
        "totalDwellSeconds": 0,
        "ctaClicks": 0,
        "questionsAsked": 0,
        "reopens": 0,
        "engagementScore": 0,
    }


def _score(agg: dict) -> int:
    """A simple 0–100 engagement score from the weighted signals (deterministic)."""
    score = (
        agg["opened"] * 10
        + agg["slidesViewed"] * 5
        + min(agg["totalDwellSeconds"] // 30, 20)
        + agg["ctaClicks"] * 15
        + agg["questionsAsked"] * 12
        + agg["reopens"] * 8
    )
    return max(0, min(100, score))


def pitch_engagement_for_lead(lead) -> dict:
    """Aggregate pitch telemetry for a single lead into cockpit fields."""
    agg = _empty_engagement()
    try:
        from apps.agents.models import AgentRun

        runs = AgentRun.objects.filter(lead=lead, agent_key="pitch")
        agg["opened"] = runs.count()
        # Pull any recorded pitch.* events from the run meta/output where present.
        for run in runs:
            events = (run.output or {}).get("events", []) if isinstance(run.output, dict) else []
            for ev in events:
                _accumulate(agg, ev)
    except Exception:  # noqa: BLE001
        logger.debug("pitch_engagement_for_lead: no telemetry available")
    agg["engagementScore"] = _score(agg)
    return agg


def _accumulate(agg: dict, event: dict) -> None:
    name = (event or {}).get("type", "")
    if name == "slide_viewed":
        agg["slidesViewed"] += 1
    elif name == "slide_dwell":
        agg["totalDwellSeconds"] += int(event.get("seconds", 0) or 0)
    elif name == "cta_clicked":
        agg["ctaClicks"] += 1
    elif name == "question_asked":
        agg["questionsAsked"] += 1
    elif name == "reopened":
        agg["reopens"] += 1


def pitch_engagement_overview(*, days: int = 30) -> dict:
    """Platform-wide pitch aggregation for the analytics/pitch/ endpoint."""
    since = timezone.now() - timedelta(days=max(1, min(days, 365)))
    overview = {
        "totalPitchesOpened": 0,
        "totalCtaClicks": 0,
        "totalQuestionsAsked": 0,
        "byPitchType": {},
        "windowDays": days,
    }
    try:
        from apps.agents.models import AgentRun

        runs = AgentRun.objects.filter(agent_key="pitch", created_at__gte=since)
        overview["totalPitchesOpened"] = runs.count()
        for run in runs:
            out = run.output if isinstance(run.output, dict) else {}
            ptype = out.get("pitchType", "unknown")
            overview["byPitchType"][ptype] = overview["byPitchType"].get(ptype, 0) + 1
            for ev in out.get("events", []) or []:
                if (ev or {}).get("type") == "cta_clicked":
                    overview["totalCtaClicks"] += 1
                elif (ev or {}).get("type") == "question_asked":
                    overview["totalQuestionsAsked"] += 1
    except Exception:  # noqa: BLE001
        logger.debug("pitch_engagement_overview: no telemetry available")
    return overview
