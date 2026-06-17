"""
Lead scorer.

Composes the five category scorers into a full breakdown + total, and classifies the
tier. This is the authoritative server-side equivalent of
``itrix-web/src/lib/scoring/leadScorer.ts``; given the same answers it returns the same
breakdown and total, so the public site's instant estimate matches the backend result.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.scoring.services.budget_authority import score_budget_authority
from apps.scoring.services.license_potential import score_license_potential
from apps.scoring.services.score_weights import SCORING_CATEGORIES
from apps.scoring.services.strategic_fit import score_strategic_fit
from apps.scoring.services.technical_fit import score_technical_fit
from apps.scoring.services.tier_classifier import classify_with_label
from apps.scoring.services.urgency_scorer import score_urgency


@dataclass
class ScoreResult:
    breakdown: dict[str, int]
    total: int
    tier: int
    tier_label: str

    def to_dict(self) -> dict:
        return {
            "breakdown": self.breakdown,
            "total": self.total,
            "tier": self.tier,
            "tier_label": self.tier_label,
        }


class LeadScorer:
    """Authoritative lead scoring."""

    @staticmethod
    def score(answers: dict) -> ScoreResult:
        breakdown = {
            "strategic_fit": score_strategic_fit(answers),
            "technical_fit": score_technical_fit(answers),
            "urgency": score_urgency(answers),
            "budget_authority": score_budget_authority(answers),
            "license_potential": score_license_potential(answers),
        }
        # Sum in canonical category order for determinism.
        total = sum(breakdown[c] for c in SCORING_CATEGORIES)
        tier, label = classify_with_label(total)
        return ScoreResult(breakdown=breakdown, total=total, tier=tier, tier_label=label)


def score_answers(answers: dict) -> ScoreResult:
    """Module-level convenience wrapper."""
    return LeadScorer.score(answers)
