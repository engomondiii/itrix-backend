"""
Tier classifier.

Maps a 0–100 total to a tier (1–4) using the band boundaries shared with the frontend
and the dashboard (``80 / 60 / 40``):

    Tier 1 Strategic    80–100
    Tier 2 Qualified    60–79
    Tier 3 Nurture      40–59
    Tier 4 Exploratory   0–39
"""

from __future__ import annotations

TIER_LABELS: dict[int, str] = {
    1: "Strategic",
    2: "Qualified",
    3: "Nurture",
    4: "Exploratory",
}

# Human-response SLA (hours) per tier; None = no human follow-up (matches dashboard).
TIER_RESPONSE_HOURS: dict[int, int | None] = {1: 24, 2: 48, 3: 24, 4: None}


def classify_tier(total: int) -> int:
    if total >= 80:
        return 1
    if total >= 60:
        return 2
    if total >= 40:
        return 3
    return 4


def tier_label(tier: int) -> str:
    return TIER_LABELS.get(tier, "Exploratory")


def classify_with_label(total: int) -> tuple[int, str]:
    tier = classify_tier(total)
    return tier, tier_label(tier)
