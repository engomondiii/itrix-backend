"""
Buyer agent (Backend v4 §2.2) — stakeholder / champion / blocker / approval-path map.

INTERNAL (team plane): maps the buying group from the lead's role + org signals — likely
champion, economic buyer, technical evaluator, and blockers — plus the approval path.
Claim level L2 internal. Deterministic fallback builds a sensible generic map from role.
"""

# SECURITY INVARIANT 2 (Backend v6.0 §Phase 1): retrieval context is DERIVED from the
# identity plane via ``ctx.retrieval_context``. This agent previously passed a literal
# ``context="internal"``, which meant an anonymous visitor could be answered from
# internal_only chunks. Never pass a literal here.

from __future__ import annotations

import logging

from apps.agents.services.base import BaseAgent
from apps.agents.services.context import AgentContext
from apps.agents.services.output_contract import AgentOutput

logger = logging.getLogger("itrix")

_JSON = (
    "Respond ONLY with a JSON object: "
    '{"champion": string, "economicBuyer": string, "technicalEvaluator": string, '
    '"likelyBlockers": [string], "approvalPath": [string]}. Internal map; qualitative only.'
)


class BuyerAgent(BaseAgent):
    key = "buyer"
    name = "Buyer agent"
    default_claim_level = 2

    def run_ai(self, ctx: AgentContext) -> AgentOutput:
        from apps.ai_engine.services.claude_client import AIEngineDisabled, ClaudeClient
        from apps.ai_engine.services.system_prompt_builder import build_system_prompt

        try:
            system = build_system_prompt(
                product_route=ctx.product_route, license_pathway=ctx.license_pathway,
                tier=ctx.tier, pressures=ctx.pressures, chunks=[], context=ctx.retrieval_context,
            )
            role = (ctx.extra or {}).get("role", "")
            raw = ClaudeClient().complete(system=system, user=f"Lead role/org: {role}\nProblem:\n{ctx.prompt}\n\n{_JSON}", max_tokens=700)
        except AIEngineDisabled:
            return self.run_fallback(ctx)
        import json
        try:
            data = json.loads(raw.strip().strip("`"))
            return AgentOutput(payload=data, used_ai=True, claim_level=self.default_claim_level)
        except Exception:  # noqa: BLE001
            return self.run_fallback(ctx)

    def run_fallback(self, ctx: AgentContext) -> AgentOutput:
        return AgentOutput(
            payload={
                "champion": "The technical lead who raised the bottleneck.",
                "economicBuyer": "Engineering or R&D budget owner.",
                "technicalEvaluator": "Senior engineer who would run an evaluation.",
                "likelyBlockers": ["Procurement / security review", "Integration risk concerns"],
                "approvalPath": ["Technical validation", "Budget sign-off", "Legal / NDA"],
            },
            used_ai=False,
            claim_level=0,
        )
