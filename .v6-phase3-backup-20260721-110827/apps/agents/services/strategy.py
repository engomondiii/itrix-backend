"""
Strategy agent (Backend v4 §2.2) — GTM logic, account priority, commercial path.

INTERNAL (team plane) analysis: given a lead's signals, it produces a go-to-market read
— account priority, the recommended commercial path, and the reasoning. Claim level L2
(qualitative, internal). AI path retrieves strategic/commercialization cores; the
deterministic fallback derives a sound read from tier + route + intent.
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

_ROUTE_TO_NAMESPACE = {
    "alpha_compute": "alpha-compute",
    "alpha_core": "alpha-core",
    "both": "alpha-compute",
    "general": "general",
}

_JSON = (
    "Respond ONLY with a JSON object: "
    '{"accountPriority": "high"|"medium"|"low", '
    '"commercialPath": string, "rationale": string, '
    '"recommendedActions": [string]}. Internal strategic read; qualitative only.'
)


class StrategyAgent(BaseAgent):
    key = "strategy"
    name = "Strategy agent"
    default_claim_level = 2

    def run_ai(self, ctx: AgentContext) -> AgentOutput:
        from apps.ai_engine.services.claude_client import AIEngineDisabled, ClaudeClient
        from apps.ai_engine.services.knowledge_retriever import KnowledgeRetriever
        from apps.ai_engine.services.system_prompt_builder import build_system_prompt

        ns = _ROUTE_TO_NAMESPACE.get(ctx.product_route, "general")
        chunks = KnowledgeRetriever().retrieve(ctx.prompt or "strategy", namespace=ns, top_k=6, context=ctx.retrieval_context)
        try:
            system = build_system_prompt(
                product_route=ctx.product_route, license_pathway=ctx.license_pathway,
                tier=ctx.tier, pressures=ctx.pressures, chunks=chunks, context=ctx.retrieval_context,
            )
            raw = ClaudeClient().complete(system=system, user=f"Lead context:\n{ctx.prompt}\n\n{_JSON}", max_tokens=800)
        except AIEngineDisabled:
            return self.run_fallback(ctx)
        import json
        try:
            data = json.loads(raw.strip().strip("`"))
            return AgentOutput(payload=data, chunk_ids=[c.get("chunk_id","") for c in chunks if c.get("chunk_id")], used_ai=True, claim_level=self.default_claim_level)
        except Exception:  # noqa: BLE001
            return self.run_fallback(ctx)

    def run_fallback(self, ctx: AgentContext) -> AgentOutput:
        priority = "high" if ctx.tier in (1, 2) else ("medium" if ctx.tier == 3 else "low")
        path = ctx.license_pathway or "non_exclusive"
        return AgentOutput(
            payload={
                "accountPriority": priority,
                "commercialPath": path,
                "rationale": f"Tier {ctx.tier} lead on the {ctx.product_route} route; priority follows the tier band and the expressed commercial path.",
                "recommendedActions": [
                    "Confirm the primary bottleneck in a short call.",
                    "Offer a scoped evaluation to convert qualitative fit into evidence.",
                ],
            },
            used_ai=False,
            claim_level=0,
        )
