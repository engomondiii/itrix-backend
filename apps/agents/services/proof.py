"""
Proof agent (Backend v4 §2.2) — evidence map, proof pack, claim-support note.

Claim level L3 with a citation requirement: every proof point must reference an approved
chunk. Queues for approval by default. The deterministic fallback returns a conservative
proof scaffold that defers quantitative evidence to a validated evaluation.
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
    '{"proofPoints": [{"claim": string, "support": string, "chunkId": string}], '
    '"evidenceGaps": [string]}. Every proof point MUST cite a chunkId from the provided '
    "evidence; if none supports it, put it in evidenceGaps instead. No unapproved numbers."
)


class ProofAgent(BaseAgent):
    key = "proof"
    name = "Proof agent"
    default_claim_level = 3

    def run_ai(self, ctx: AgentContext) -> AgentOutput:
        from apps.ai_engine.services.claude_client import AIEngineDisabled, ClaudeClient
        from apps.ai_engine.services.knowledge_retriever import KnowledgeRetriever
        from apps.ai_engine.services.system_prompt_builder import build_system_prompt

        chunks = KnowledgeRetriever().retrieve(ctx.prompt or "proof", namespace="general", top_k=8, context=ctx.retrieval_context)
        try:
            system = build_system_prompt(
                product_route=ctx.product_route, license_pathway=ctx.license_pathway,
                tier=ctx.tier, pressures=ctx.pressures, chunks=chunks, context=ctx.retrieval_context,
            )
            raw = ClaudeClient().complete(system=system, user=f"Assemble a proof pack for:\n{ctx.prompt}\n\n{_JSON}", max_tokens=1000)
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
                "proofPoints": [],
                "evidenceGaps": [
                    "Quantitative performance evidence is deferred to a scoped evaluation on your data.",
                    "Public materials describe the approach qualitatively; specifics are NDA-gated.",
                ],
            },
            used_ai=False,
            claim_level=3,
        )
