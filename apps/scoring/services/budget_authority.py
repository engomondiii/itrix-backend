"""
Budget & authority scorer (max 15).

Blends decision role (Q7) and budget state (Q8) as their average, capped at the
category weight. Mirrors ``itrix-web`` leadScorer budget_authority.
"""

from __future__ import annotations

from apps.routing.services.routing_rules import single
from apps.scoring.services.score_weights import (
    CATEGORY_WEIGHTS,
    Q7_WEIGHTS,
    Q8_WEIGHTS,
    weight_for,
)


def score_budget_authority(answers: dict) -> int:
    blended = (
        weight_for(Q7_WEIGHTS, single(answers.get("Q7")))
        + weight_for(Q8_WEIGHTS, single(answers.get("Q8")))
    ) / 2
    return min(CATEGORY_WEIGHTS["budget_authority"], round(blended))
