"""
Urgency scorer (max 20).

Blends timeline (Q4) and bottleneck severity (Q5) as their average, capped at the
category weight. Mirrors ``itrix-web`` leadScorer urgency.
"""

from __future__ import annotations

from apps.routing.services.routing_rules import single
from apps.scoring.services.score_weights import (
    CATEGORY_WEIGHTS,
    Q4_WEIGHTS,
    Q5_WEIGHTS,
    weight_for,
)


def score_urgency(answers: dict) -> int:
    blended = (
        weight_for(Q4_WEIGHTS, single(answers.get("Q4")))
        + weight_for(Q5_WEIGHTS, single(answers.get("Q5")))
    ) / 2
    return min(CATEGORY_WEIGHTS["urgency"], round(blended))
