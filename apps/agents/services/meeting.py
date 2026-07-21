"""
Meeting agent (Backend v4 §2.2) — brief, agenda, follow-up email, CRM note.

Produces a compact meeting kit for the team (and, where appropriate, a portal-facing
agenda). Claim level L2. Deterministic fallback assembles a standard discovery-call kit
from the lead's route + pressures.
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
    '{"brief": string, "agenda": [string], "followUpEmail": string, "crmNote": string}. '
    "Qualitative; no benchmark numbers or guarantees."
)


class MeetingAgent(BaseAgent):
    key = "meeting"
    name = "Meeting agent"
    default_claim_level = 2

    def run_ai(self, ctx: AgentContext) -> AgentOutput:
        from apps.ai_engine.services.claude_client import AIEngineDisabled, ClaudeClient
        from apps.ai_engine.services.system_prompt_builder import build_system_prompt

        try:
            system = build_system_prompt(
                product_route=ctx.product_route, license_pathway=ctx.license_pathway,
                tier=ctx.tier, pressures=ctx.pressures, chunks=[], context=ctx.retrieval_context,
            )
            raw = ClaudeClient().complete(system=system, user=f"Prep a discovery meeting kit for:\n{ctx.prompt}\n\n{_JSON}", max_tokens=900)
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
                "brief": "A short discovery call to confirm the bottleneck and scope a possible evaluation.",
                "agenda": [
                    "Confirm the workload and the primary pressure.",
                    "Walk through where the approach may fit.",
                    "Discuss what a scoped evaluation would measure.",
                    "Agree next steps and owners.",
                ],
                "followUpEmail": "Thanks for the conversation — here's a short recap and a suggested scoped evaluation as the next step.",
                "crmNote": f"Discovery call for a Tier {ctx.tier} {ctx.product_route} lead; next step: scoped evaluation.",
            },
            used_ai=False,
            claim_level=0,
        )
