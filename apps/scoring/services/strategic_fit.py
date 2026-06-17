"""
Strategic-fit scorer (max 25).

Driven by organization type (Q6): hardware/chip and cloud/infra orgs are the highest
strategic fit for the target market; research and individuals score lower. Mirrors the
frontend's strategic_fit derivation.
"""

from __future__ import annotations

from apps.routing.services.routing_rules import single
from apps.scoring.services.score_weights import CATEGORY_WEIGHTS, Q6_WEIGHTS, weight_for


def score_strategic_fit(answers: dict) -> int:
    points = weight_for(Q6_WEIGHTS, single(answers.get("Q6")))
    return min(CATEGORY_WEIGHTS["strategic_fit"], points)
