"""
Scoring-related answer fixtures for tests.

Re-exports the canonical HIGH/LOW answer sets and adds a few mid-tier sets so scoring and
tier tests can assert each band boundary. Pure data — no DB models.
"""

from __future__ import annotations

from tests.factories.review_factory import HIGH_SCORE_ANSWERS, LOW_SCORE_ANSWERS  # noqa: F401

# Mid sets engineered to land in tiers 2 and 3.
TIER2_ANSWERS = {
    "Q1": "python_scipy",
    "Q2": ["speed", "cost"],
    "Q3": "linear_algebra",
    "Q4": "quarter",
    "Q5": "significant",
    "Q6": "enterprise_rd",
    "Q7": "influencer",
    "Q8": "planning",
    "Q9": "non_exclusive",
}

TIER3_ANSWERS = {
    "Q1": "python_scipy",
    "Q2": ["cost"],
    "Q3": "unsure",
    "Q4": "year",
    "Q5": "moderate",
    "Q6": "research",
    "Q7": "evaluator",
    "Q8": "none_yet",
    "Q9": "product_only",
}

# A representation-shaped set that should route to ALPHA Compute.
REPRESENTATION_ANSWERS = {
    "Q1": "python_scipy",
    "Q2": ["cost", "stability_accuracy"],
    "Q3": "linear_algebra",
    "Q4": "quarter",
    "Q5": "significant",
    "Q6": "enterprise_rd",
    "Q7": "influencer",
    "Q8": "planning",
    "Q9": "non_exclusive",
}

# An execution-shaped set that should route to ALPHA Core.
EXECUTION_ANSWERS = {
    "Q1": "hardware",
    "Q2": ["memory_data_movement", "hardware_utilization"],
    "Q3": "conservation",
    "Q4": "now",
    "Q5": "critical",
    "Q6": "hardware_chip",
    "Q7": "decision_maker",
    "Q8": "allocated",
    "Q9": "exclusive",
}
