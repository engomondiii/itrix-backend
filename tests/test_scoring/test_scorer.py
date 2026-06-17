"""Lead-scorer tests — breakdown shape, totals, and frontend parity."""

from __future__ import annotations

from apps.scoring.services.score_weights import CATEGORY_WEIGHTS, SCORING_TOTAL
from apps.scoring.services.scorer import LeadScorer, score_answers
from tests.factories.scoring_factory import (
    HIGH_SCORE_ANSWERS,
    LOW_SCORE_ANSWERS,
    TIER2_ANSWERS,
)


def test_weights_sum_to_100():
    assert SCORING_TOTAL == 100
    assert sum(CATEGORY_WEIGHTS.values()) == 100


def test_breakdown_has_all_five_categories():
    result = LeadScorer.score(HIGH_SCORE_ANSWERS)
    assert set(result.breakdown.keys()) == {
        "strategic_fit",
        "technical_fit",
        "urgency",
        "budget_authority",
        "license_potential",
    }


def test_no_category_exceeds_its_weight():
    result = LeadScorer.score(HIGH_SCORE_ANSWERS)
    for category, points in result.breakdown.items():
        assert points <= CATEGORY_WEIGHTS[category]


def test_total_equals_sum_of_breakdown():
    result = LeadScorer.score(TIER2_ANSWERS)
    assert result.total == sum(result.breakdown.values())


def test_high_answers_score_tier_1():
    result = LeadScorer.score(HIGH_SCORE_ANSWERS)
    assert result.total >= 80
    assert result.tier == 1


def test_low_answers_score_tier_4():
    result = LeadScorer.score(LOW_SCORE_ANSWERS)
    assert result.total < 40
    assert result.tier == 4


def test_score_answers_wrapper_matches_class():
    a = LeadScorer.score(TIER2_ANSWERS)
    b = score_answers(TIER2_ANSWERS)
    assert a.breakdown == b.breakdown and a.total == b.total


def test_total_in_valid_range():
    for answers in (HIGH_SCORE_ANSWERS, LOW_SCORE_ANSWERS, TIER2_ANSWERS):
        result = LeadScorer.score(answers)
        assert 0 <= result.total <= 100
