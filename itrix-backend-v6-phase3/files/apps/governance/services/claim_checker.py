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


# ─────────────────────────────────────────────────────────────────────────────
# The shared pattern set (Backend v6.0 §11.1)
# ─────────────────────────────────────────────────────────────────────────────
# THE PROHIBITED-PATTERN SET HAS EXACTLY ONE DEFINITION.
#
# It is consumed by BOTH ``prohibited_language_checker`` (at settle) and
# ``governance.services.stream_guard`` (mid-stream), so a pattern cannot be enforced at
# settle but missed mid-stream. Surface 2 renders this same set in
# ``governance/streaming`` precisely so a divergence would be VISIBLE.
#
# If you add a pattern, add it to ``prohibited_language_checker`` and both paths pick it
# up. Do not restate patterns in the guard.


def shared_pattern_set() -> dict:
    """
    The single pattern set, exposed for the stream guard and for cockpit display.

    Returns the raw pattern strings by category. Compilation happens in the guard (once
    per process); this function is the source of truth for WHAT is enforced, not HOW.
    """
    from apps.ai_engine.services import prohibited_language_checker as plc

    return {
        "hard_block": list(plc.HARD_BLOCK_PATTERNS),
        "prohibited_claims": list(plc.PROHIBITED_CLAIMS),
        "canonical_substitutions": [raw for raw, _ in plc.CANONICAL_SUBSTITUTIONS],
        "risky": list(plc._RISKY_PATTERNS),
    }


def pattern_set_fingerprint() -> str:
    """
    A stable fingerprint of the shared set.

    The cockpit displays this alongside the guard's own fingerprint. If they ever differ,
    the two enforcement paths have drifted apart and the discrepancy is visible rather
    than silent — which is the entire point of displaying the set.
    """
    import hashlib
    import json

    payload = json.dumps(shared_pattern_set(), sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────────────────────
# v6.0 Phase 2: governance covers artifacts and generated questions too
# ─────────────────────────────────────────────────────────────────────────────
# §Phase 2: the claim checker "governs artifacts and generated questions, not only
# messages". Everything outbound goes through the same gate — a brief that asserts what
# a message may not assert would simply move the problem.

# The commercial-in-support pattern set is SINGLE-SOURCED in
# ``prohibited_language_checker`` (§11.1), so it is enforced identically here at settle
# and mid-stream by the guard. Do not restate the patterns in this module.


def check_support_reply(text: str) -> GovernanceDecision:
    """
    A support question is NEVER answered with a commercial answer (§19.5).

        A support reply helps with the problem and stops. It does not mention another
        workload, an expansion, a renewal, or a next agreement — NO MATTER HOW NATURAL
        THE SEGUE SEEMS.

    Enforced in the claim checker rather than by prompt wording, because "no matter how
    natural the segue seems" is precisely the judgement a helpful model gets wrong.
    """
    from apps.ai_engine.services.prohibited_language_checker import (
        find_commercial_in_support,
        has_commercial_in_support,
    )

    decision = check(text, claim_level=1, context="support")
    if decision.status == GOV_BLOCKED:
        return decision

    if has_commercial_in_support(text):
        matched = find_commercial_in_support(text)
        return GovernanceDecision(
            status=GOV_BLOCKED,
            text=decision.text,
            claim_level=decision.claim_level,
            violations=[*decision.violations,
                        *(f"commercial_in_support:{m}" for m in matched)],
            reason="A support reply may not mention a commercial next step.",
        )
    return decision


def check_generated_question(text: str) -> GovernanceDecision:
    """
    A generated question may ASK, never ASSERT (§5.4).

    Bound to Claim-Card level 1, so anything above auto-approve is refused outright
    rather than queued — a question is not worth a human approval round trip; we ask the
    approved bank version instead.

    ── WHY THIS DELEGATES TO THE GENERATOR'S GUARD ─────────────────────────
    The prohibited-language checker SCRUBS: it rewrites "guaranteed" into softer wording
    and then auto-approves the result. That is right for a message, where the scrubbed
    text is still a usable answer. It is WRONG for a question — a question that had to be
    scrubbed should not be asked at all, because the approved bank version is right there
    and costs nothing.

    So the question-specific rules live in ONE place (``question_generator.check_candidate``)
    and this function calls them, rather than restating them and drifting.
    """
    try:
        from apps.agents.services.question_generator import check_candidate

        reason = check_candidate(text)
        if reason:
            return GovernanceDecision(
                status=GOV_BLOCKED,
                text=text,
                claim_level=1,
                violations=[reason],
                reason=f"A generated question must ask, never assert ({reason}).",
            )
    except Exception:  # noqa: BLE001
        logger.exception("question guard unavailable; refusing conservatively")
        return GovernanceDecision(
            status=GOV_BLOCKED, text=text, claim_level=1,
            reason="question guard unavailable",
        )

    decision = check(text, claim_level=1, context="public")
    if decision.status != GOV_AUTO_APPROVED:
        return GovernanceDecision(
            status=GOV_BLOCKED,
            text=decision.text,
            claim_level=1,
            violations=decision.violations,
            reason="A generated question must clear governance at claim level 1.",
        )
    return decision


def check_artifact(payload_text: str, *, claim_level: int = 2) -> GovernanceDecision:
    """Govern an artifact's text exactly like a message."""
    return check(payload_text, claim_level=claim_level, context="public")
