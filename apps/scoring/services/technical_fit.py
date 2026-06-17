"""
Technical-fit scorer (max 25).

Derived from the workload structure (Q3), the runtime environment (Q1), and the number
of selected pressure areas (Q2):

* structure: mixed=14, a concrete structure=12, unsure=5, none=0
* environment present: +8
* +1 per selected pressure, capped at 3

Capped at the category weight. Mirrors ``itrix-web`` leadScorer technical_fit.
"""

from __future__ import annotations

from apps.routing.services.routing_rules import multi, single
from apps.scoring.services.score_weights import CATEGORY_WEIGHTS


def score_technical_fit(answers: dict) -> int:
    structure = single(answers.get("Q3"))
    if structure == "mixed":
        structure_pts = 14
    elif structure == "unsure":
        structure_pts = 5
    elif structure:
        structure_pts = 12
    else:
        structure_pts = 0

    env_pts = 8 if single(answers.get("Q1")) else 0
    pressure_pts = min(3, len(multi(answers.get("Q2"))))

    return min(CATEGORY_WEIGHTS["technical_fit"], structure_pts + env_pts + pressure_pts)
