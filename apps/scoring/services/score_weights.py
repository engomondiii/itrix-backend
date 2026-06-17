"""
Scoring weights & shared option tables.

Single source of truth for the 0–100 weighting and the per-option point tables, all
mirrored from the frontend (``itrix-web/src/constants/scoring.ts`` and
``src/config/review.config.ts``) so the client's provisional estimate and this
authoritative server score line up exactly.

    strategic 25 / technical 25 / urgency 20 / budget 15 / license 15  = 100
"""

from __future__ import annotations

CATEGORY_WEIGHTS: dict[str, int] = {
    "strategic_fit": 25,
    "technical_fit": 25,
    "urgency": 20,
    "budget_authority": 15,
    "license_potential": 15,
}

CATEGORY_LABELS: dict[str, str] = {
    "strategic_fit": "Strategic fit",
    "technical_fit": "Technical fit",
    "urgency": "Urgency",
    "budget_authority": "Budget & authority",
    "license_potential": "License-out potential",
}

SCORING_CATEGORIES: list[str] = list(CATEGORY_WEIGHTS.keys())
SCORING_TOTAL: int = sum(CATEGORY_WEIGHTS.values())  # 100

# ── Per-option weight tables (Q4, Q5, Q6, Q7, Q8, Q9) ────────────────────────
Q4_WEIGHTS = {"now": 20, "quarter": 15, "year": 8, "exploring": 3}          # urgency: timeline
Q5_WEIGHTS = {"critical": 20, "significant": 14, "moderate": 8, "minor": 3}  # urgency: severity
Q6_WEIGHTS = {                                                               # strategic: org
    "hardware_chip": 25,
    "cloud_infra": 22,
    "enterprise_rd": 18,
    "research": 12,
    "individual": 5,
}
Q7_WEIGHTS = {"decision_maker": 15, "influencer": 10, "evaluator": 7, "curious": 2}  # budget: role
Q8_WEIGHTS = {"allocated": 15, "planning": 10, "none_yet": 4}                # budget: budget state
Q9_WEIGHTS = {"exclusive": 15, "non_exclusive": 11, "product_only": 6, "unsure": 3}  # license intent


def weight_for(table: dict[str, int], key: str | None) -> int:
    return table.get(key, 0) if key else 0
