"""
License-out potential scorer (max 15).

Driven by the licensing-interest answer (Q9). Mirrors ``itrix-web`` leadScorer
license_potential.
"""

from __future__ import annotations

from apps.routing.services.routing_rules import single
from apps.scoring.services.score_weights import CATEGORY_WEIGHTS, Q9_WEIGHTS, weight_for


def score_license_potential(answers: dict) -> int:
    points = weight_for(Q9_WEIGHTS, single(answers.get("Q9")))
    return min(CATEGORY_WEIGHTS["license_potential"], points)
