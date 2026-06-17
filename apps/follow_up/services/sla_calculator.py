"""
SLA calculator.

Computes the follow-up due time from a lead's tier, using the same SLA hours the dashboard
uses (Tier 1: 24h, Tier 2: 48h, Tier 3: 24h automated, Tier 4: none). Shares the source of
truth with scoring.tier_classifier.TIER_RESPONSE_HOURS.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.scoring.services.tier_classifier import TIER_RESPONSE_HOURS


def sla_hours_for_tier(tier: int) -> int | None:
    return TIER_RESPONSE_HOURS.get(tier)


def due_at_for_tier(tier: int, *, start=None):
    """Return the due datetime for a tier, or None when the tier has no SLA."""
    hours = sla_hours_for_tier(tier)
    if hours is None:
        return None
    return (start or timezone.now()) + timedelta(hours=hours)
