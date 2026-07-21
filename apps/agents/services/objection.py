"""
Objection agent (Backend v4 §2.2) — objection book, talk tracks, deal-risk memo.

Claim level L3 (draft — needs human approval before it reaches a client). Produces an
objection→response book and a deal-risk memo. Because default_claim_level = 3 exceeds the
auto-approve threshold, the runtime queues its output for approval rather than delivering
it directly.
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
    '{"objections": [{"objection": string, "response": string}], '
    '"dealRisks": [string]}. Qualitative; hedge all claims; no benchmark numbers.'
)


class ObjectionAgent(BaseAgent):
    key = "objection"
    name = "Objection agent"
    default_claim_level = 3

    def run_ai(self, ctx: AgentContext) -> AgentOutput:
        from apps.ai_engine.services.claude_client import AIEngineDisabled, ClaudeClient
        from apps.ai_engine.services.knowledge_retriever import KnowledgeRetriever
        from apps.ai_engine.services.system_prompt_builder import build_system_prompt

        chunks = KnowledgeRetriever().retrieve(ctx.prompt or "objection", namespace="general", top_k=6, context=ctx.retrieval_context)
        try:
            system = build_system_prompt(
                product_route=ctx.product_route, license_pathway=ctx.license_pathway,
                tier=ctx.tier, pressures=ctx.pressures, chunks=chunks, context=ctx.retrieval_context,
            )
            raw = ClaudeClient().complete(system=system, user=f"Build an objection book for:\n{ctx.prompt}\n\n{_JSON}", max_tokens=1000)
        except AIEngineDisabled:
            return self.run_fallback(ctx)
        import json
        try:
            data = json.loads(raw.strip().strip("`"))
            return AgentOutput(payload=data, chunk_ids=[c.get("chunk_id","") for c in chunks if c.get("chunk_id")], used_ai=True, claim_level=self.default_claim_level)
        except Exception:  # noqa: BLE001
            return self.run_fallback(ctx)

    def run_fallback(self, ctx: AgentContext) -> AgentOutput:
        return AgentOutput(
            payload={
                "objections": [
                    {"objection": "How do we know it will work on our workload?",
                     "response": "We propose a scoped evaluation on representative work before any commitment — fit is confirmed with evidence, not asserted."},
                    {"objection": "Integration looks risky.",
                     "response": "We describe the integration path in non-confidential terms first and keep specifics to an NDA-gated technical discussion."},
                ],
                "dealRisks": ["Unconfirmed fit until evaluation", "Procurement / security review timing"],
            },
            used_ai=False,
            claim_level=3,
        )
