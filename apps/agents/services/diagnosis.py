"""
Diagnosis agent — the refactor target of ai_engine/services/rag_pipeline.py.

Same flow, same graceful degradation:

    retrieve disclosure-filtered knowledge → build system prompt → ask Claude (JSON)
    → assemble + guard the response → return a safe Problemology-structured partial.

The AI path reuses the shipped ai_engine services verbatim (KnowledgeRetriever,
build_system_prompt, ClaudeClient, assemble) so behaviour is byte-for-byte the same as
the old ``run_rag``. The deterministic fallback returns an empty payload, exactly like
the old pipeline, so ``result_generator`` produces the full page from its builders.

``rag_pipeline.run_rag`` is kept as a thin shim that delegates here, so existing
imports/tests keep working (see apps/ai_engine/services/rag_pipeline.py).
"""

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

_RESULT_JSON_INSTRUCTION = (
    "Respond ONLY with a JSON object (no prose, no markdown fences) with keys: "
    '"problemMirror" (string), "alphaFitSummary" (string), '
    '"diagnosis" (array of objects with "pressure","observation","itrixInterpretation","alphaRole"), '
    '"kpiPreview" (array of objects with "label","metric"), '
    '"recommendedNextStep" (string). Keep all language qualitative and within the claims discipline.'
)

# Narrative fields the Diagnosis agent may contribute to the result page.
NARRATIVE_KEYS = ("problemMirror", "alphaFitSummary", "diagnosis", "kpiPreview", "recommendedNextStep")


class DiagnosisAgent(BaseAgent):
    key = "diagnosis"
    name = "Diagnosis agent"
    default_claim_level = 2  # qualitative result-page narrative — auto-approves at default

    def _namespace(self, ctx: AgentContext) -> str:
        return _ROUTE_TO_NAMESPACE.get(ctx.product_route, "general")

    def retrieve(self, ctx: AgentContext, *, top_k: int = 8) -> list[dict]:
        """Disclosure-filtered retrieval (works offline via keyword fallback)."""
        from apps.ai_engine.services.knowledge_retriever import KnowledgeRetriever

        return KnowledgeRetriever().retrieve(
            ctx.prompt,
            namespace=self._namespace(ctx),
            top_k=top_k,
            context=self._retrieval_context(ctx),
        )

    @staticmethod
    def _retrieval_context(ctx: AgentContext) -> str:
        """
        SECURITY INVARIANT 2 — delegate, never derive locally.

        This previously derived the retrieval context from ``context_label``, which is a
        DISPLAY label rather than an identity plane. An anonymous visitor holding a
        client_page capability token has ``context_label == "client_page"`` while still
        being on the PUBLIC plane — so the old rule could hand nda_only chunks to an
        unidentified visitor.

        ``ctx.retrieval_context`` is derived from the plane and nothing else.
        """
        return ctx.retrieval_context

    def run_ai(self, ctx: AgentContext, *, top_k: int = 8) -> AgentOutput:
        from apps.ai_engine.services.claude_client import AIEngineDisabled, ClaudeClient
        from apps.ai_engine.services.response_assembler import assemble
        from apps.ai_engine.services.system_prompt_builder import build_system_prompt

        chunks = self.retrieve(ctx, top_k=top_k)
        evidence = "\n".join(c.get("text", "") for c in chunks)

        try:
            system = build_system_prompt(
                product_route=ctx.product_route,
                license_pathway=ctx.license_pathway,
                tier=ctx.tier,
                pressures=ctx.pressures,
                chunks=chunks,
                context=self._retrieval_context(ctx),
            )
            user = f"Visitor's description of their problem:\n{ctx.prompt}\n\n{_RESULT_JSON_INSTRUCTION}"
            raw = ClaudeClient().complete(system=system, user=user, max_tokens=1200)
            partial = assemble(raw, evidence=evidence)
        except AIEngineDisabled:
            return AgentOutput(payload={}, chunk_ids=[c.get("chunk_id", "") for c in chunks], used_ai=False)

        return AgentOutput(
            payload={k: partial[k] for k in NARRATIVE_KEYS if partial.get(k)},
            chunk_ids=[c.get("chunk_id", "") for c in chunks if c.get("chunk_id")],
            used_ai=True,
            claim_level=self.default_claim_level,
        )

    def run_fallback(self, ctx: AgentContext) -> AgentOutput:
        """
        Deterministic fallback: empty narrative payload. The result_generator's own
        deterministic builders then produce the full page — identical to the shipped
        behaviour when the AI engine is off.
        """
        return AgentOutput(payload={}, chunk_ids=[], used_ai=False, claim_level=0)


# ── Backwards-compatible functional API (used by the rag_pipeline shim) ───────
class RagResult:
    """Preserves the shape the old rag_pipeline returned."""

    def __init__(self, *, partial: dict, used_ai: bool, chunks: list[dict]):
        self.partial = partial
        self.used_ai = used_ai
        self.chunks = chunks


def run_rag(
    *,
    prompt: str,
    product_route: str,
    license_pathway: str | None,
    tier: int,
    pressures: list[str],
    context: str = "public",
    top_k: int = 8,
) -> RagResult:
    """
    Diagnosis-agent-backed replacement for the old ``run_rag``. Retrieval always runs;
    generation runs only when the engine is enabled. Returns the same RagResult shape.
    """
    from django.conf import settings

    ctx = AgentContext(
        prompt=prompt,
        pressures=list(pressures or []),
        product_route=product_route,
        license_pathway=license_pathway,
        tier=tier,
        context_label=context,
        nda_signed=(context == "nda"),
    )
    agent = DiagnosisAgent()

    chunks = agent.retrieve(ctx, top_k=top_k)

    # Match the old pipeline: only call the model when the AI ENGINE flag is on. The
    # agent runtime's own ENABLE_AGENTS gate is checked by callers that go through the
    # runtime; the result-page path historically keyed on ENABLE_AI_ENGINE, preserved here.
    if not settings.ENABLE_AI_ENGINE:
        return RagResult(partial={}, used_ai=False, chunks=chunks)

    from apps.ai_engine.services.claude_client import AIEngineDisabled, ClaudeClient
    from apps.ai_engine.services.response_assembler import assemble
    from apps.ai_engine.services.system_prompt_builder import build_system_prompt

    evidence = "\n".join(c.get("text", "") for c in chunks)
    try:
        system = build_system_prompt(
            product_route=product_route,
            license_pathway=license_pathway,
            tier=tier,
            pressures=pressures,
            chunks=chunks,
            context=context,
        )
        user = f"Visitor's description of their problem:\n{prompt}\n\n{_RESULT_JSON_INSTRUCTION}"
        raw = ClaudeClient().complete(system=system, user=user, max_tokens=1200)
        partial = assemble(raw, evidence=evidence)
        return RagResult(partial=partial, used_ai=True, chunks=chunks)
    except AIEngineDisabled:
        return RagResult(partial={}, used_ai=False, chunks=chunks)
    except Exception:  # noqa: BLE001
        logger.exception("Diagnosis run_rag failed; returning deterministic-only result")
        return RagResult(partial={}, used_ai=False, chunks=chunks)
