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


def govern_text(text: str, *, claim_level: int = 1, context: str = "public") -> dict:
    """
    Govern one piece of outbound text. Returns a plain dict:
        {status, text, claim_level, requires_second_approver, violations, reason}
    where status ∈ {auto_approved, pending, blocked}. Never raises.
    """
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
