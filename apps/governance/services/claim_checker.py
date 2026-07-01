"""
Claim checker — the programmatic embodiment of the Claim-Card matrix (Backend v4 §6).

Given a piece of outbound text + its claim level, it runs the shipped guards in order
and returns a governance decision:

    1. prohibited-language post-check (scrub + hard-block on residual violations),
    2. hallucination guard (when available) — evidence-grounded phrasing,
    3. claim-level threshold — ≤ AGENT_AUTO_APPROVE_MAX_LEVEL auto-approves; above it
       queues for human approval (L4/L5 additionally require a second approver).

The checker never raises; a guard import failure degrades to the conservative decision
(treat as needing review rather than letting unapproved wording through).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.conf import settings

from apps.governance.models import SECOND_APPROVER_LEVELS

logger = logging.getLogger("itrix")

GOV_AUTO_APPROVED = "auto_approved"
GOV_PENDING = "pending"
GOV_BLOCKED = "blocked"


@dataclass
class GovernanceDecision:
    status: str                      # auto_approved | pending | blocked
    text: str                        # possibly scrubbed text
    claim_level: int
    requires_second_approver: bool = False
    violations: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def delivered(self) -> bool:
        return self.status == GOV_AUTO_APPROVED


def _threshold() -> int:
    return int(getattr(settings, "AGENT_AUTO_APPROVE_MAX_LEVEL", 2))


def check(text: str, *, claim_level: int = 1, context: str = "public") -> GovernanceDecision:
    """Run the governance pass over one outbound message."""
    original = text or ""
    scrubbed = original
    violations: list[str] = []

    # 1) Prohibited-language post-check (always runs — cheap + deterministic).
    try:
        from apps.ai_engine.services.prohibited_language_checker import find_violations, scrub

        # Hard-block patterns (unapproved benchmark numbers, competitor comparisons) can
        # never auto-deliver — force human review regardless of claim level.
        from apps.ai_engine.services.prohibited_language_checker import has_hard_block

        if has_hard_block(original):
            return GovernanceDecision(
                status=GOV_PENDING,
                text=scrub(original),
                claim_level=max(claim_level, 4),
                requires_second_approver=True,
                violations=find_violations(original),
                reason="Contains benchmark/competitor claims requiring human review.",
            )

        violations = find_violations(original)
        if violations:
            scrubbed = scrub(original)
            # If scrubbing still leaves violations, hard-block.
            if find_violations(scrubbed):
                return GovernanceDecision(
                    status=GOV_BLOCKED,
                    text=scrubbed,
                    claim_level=claim_level,
                    violations=violations,
                    reason="Residual prohibited language after scrub.",
                )
    except Exception:  # noqa: BLE001
        logger.exception("prohibited-language check failed; treating as pending")
        return GovernanceDecision(
            status=GOV_PENDING, text=original, claim_level=claim_level, reason="guard error"
        )

    # 2) Hallucination guard (optional; evidence-grounded phrasing).
    try:
        from apps.ai_engine.services import hallucination_guard as hg

        if hasattr(hg, "guard"):
            report = hg.guard(scrubbed)
            # guard() returns a GuardReport carrying the cleaned text.
            scrubbed = getattr(report, "text", None) or scrubbed
    except Exception:  # noqa: BLE001
        # Non-fatal — the prohibited-language pass already ran.
        logger.debug("hallucination guard unavailable; skipping")

    # 3) Claim-level threshold.
    if claim_level <= _threshold():
        return GovernanceDecision(
            status=GOV_AUTO_APPROVED,
            text=scrubbed,
            claim_level=claim_level,
            violations=violations,
        )

    return GovernanceDecision(
        status=GOV_PENDING,
        text=scrubbed,
        claim_level=claim_level,
        requires_second_approver=claim_level in SECOND_APPROVER_LEVELS,
        violations=violations,
        reason="Claim level exceeds auto-approve threshold.",
    )
