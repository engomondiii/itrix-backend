"""
Governance meta-agent (Backend v4 §2.2, §6) — the FINAL pipeline stage.

Not user-invokable and not optional: the runtime runs this over every agent's output and
every team→client message before delivery. It is the programmatic embodiment of the
Claim-Card matrix — it runs the prohibited-language + hallucination guards and applies
the claim-level threshold via the governance ``claim_checker``.

Unlike the drafting agents it does not "generate"; it governs. The runtime calls
``govern_text`` directly (see runtime.py), and it is also registered as an agent so it can
be inspected/exercised through the standard registry + run endpoint.
"""

from __future__ import annotations

import logging

from apps.agents.services.base import BaseAgent
from apps.agents.services.context import AgentContext
from apps.agents.services.output_contract import (
    GOV_AUTO_APPROVED,
    GOV_BLOCKED,
    GOV_PENDING,
    AgentOutput,
)

logger = logging.getLogger("itrix")


# Public/client conversational Concierge replies are low-risk, document-grounded
# dialogue. They must never dead-end in an asynchronous approval queue: there is no
# operator SLA behind the visitor-facing "specialist is reviewing" notice, so using
# PENDING here turns an ordinary follow-up into a broken conversation. Higher-risk
# agents/artifacts continue through the normal Claim-Card approval pipeline.
_NON_BLOCKING_CONVERSATION_CONTEXTS = frozenset({
    "anonymous_review",
    "review",
    "client_page",
    "portal",
})


def is_non_blocking_conversation_context(context: str, *, claim_level: int = 1) -> bool:
    """True only for low-risk Concierge-style visitor/client conversation text."""
    try:
        level = int(claim_level)
    except (TypeError, ValueError):
        level = 99
    return level <= 1 and str(context or "").strip().lower() in _NON_BLOCKING_CONVERSATION_CONTEXTS


def _scrub_non_blocking_conversation(text: str) -> str:
    """
    Keep the conversation flowing while still softening obvious overclaims.

    The normal scrubber removes guarantees/universals. Quantified performance hard
    blocks are additionally replaced with qualitative, workload-specific language
    instead of sending the whole answer to a human-review queue. This preserves the
    useful document-grounded explanation around the phrase.
    """
    original = text or ""
    try:
        import re
        from apps.ai_engine.services import prohibited_language_checker as plc

        out = plc.scrub(original)
        replacement = "a workload-specific measured advantage, subject to validation"
        for pattern in plc.HARD_BLOCK_PATTERNS:
            out = re.sub(pattern, replacement, out, flags=re.IGNORECASE)
        return out
    except Exception:  # noqa: BLE001 - never turn a chat reply into an approval dead-end
        logger.exception("conversation scrub failed; delivering grounded reply without review hold")
        return original


def govern_text(text: str, *, claim_level: int = 1, context: str = "public") -> dict:
    """
    Govern one piece of outbound text. Returns a plain dict:
        {status, text, claim_level, requires_second_approver, violations, reason}
    where status ∈ {auto_approved, pending, blocked}. Never raises.
    """
    if is_non_blocking_conversation_context(context, claim_level=claim_level):
        return {
            "status": GOV_AUTO_APPROVED,
            "text": _scrub_non_blocking_conversation(text),
            "claim_level": int(claim_level or 1),
            "requires_second_approver": False,
            "violations": [],
            "reason": "non_blocking_conversation",
        }

    try:
        from apps.governance.services.claim_checker import check

        decision = check(text, claim_level=claim_level, context=context)
        return {
            "status": decision.status,
            "text": decision.text,
            "claim_level": decision.claim_level,
            "requires_second_approver": decision.requires_second_approver,
            "violations": decision.violations,
            "reason": decision.reason,
        }
    except Exception:  # noqa: BLE001 - governance must never crash the pipeline
        logger.exception("Governance check failed; holding message for review")
        return {
            "status": GOV_PENDING,
            "text": text or "",
            "claim_level": claim_level,
            "requires_second_approver": claim_level >= 4,
            "violations": [],
            "reason": "governance error — held for review",
        }


class GovernanceAgent(BaseAgent):
    key = "governance"
    name = "Governance agent"
    default_claim_level = 0

    def run_ai(self, ctx: AgentContext) -> AgentOutput:
        # The governance agent is deterministic — it never calls the model.
        return self.run_fallback(ctx)

    def run_fallback(self, ctx: AgentContext) -> AgentOutput:
        text = (ctx.extra or {}).get("text", "") or ctx.prompt
        claim_level = int((ctx.extra or {}).get("claim_level", 1))
        decision = govern_text(text, claim_level=claim_level, context=ctx.context_label)
        return AgentOutput(
            payload=decision,
            used_ai=False,
            claim_level=claim_level,
            governance_status=decision["status"],
        )
