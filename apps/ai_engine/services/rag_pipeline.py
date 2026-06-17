"""
RAG pipeline.

End-to-end retrieval-augmented generation for the result page:

    retrieve disclosure-filtered knowledge → build system prompt → ask Claude (JSON)
    → assemble + guard the response → return a safe partial result dict.

Critically, this is **optional enrichment**. When ``ENABLE_AI_ENGINE`` is False (the Phase 2
default) — or if anything fails — ``generate_result_partial`` returns an empty dict and the
result_page service produces the full page deterministically. So the visitor journey always
works; the AI layer only enriches it when configured.
"""

from __future__ import annotations

import logging

from django.conf import settings

from apps.ai_engine.services.claude_client import AIEngineDisabled, ClaudeClient
from apps.ai_engine.services.knowledge_retriever import KnowledgeRetriever
from apps.ai_engine.services.response_assembler import assemble
from apps.ai_engine.services.system_prompt_builder import build_system_prompt

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


class RagResult:
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
    """Run retrieval + (optional) generation and return a RagResult."""
    namespace = _ROUTE_TO_NAMESPACE.get(product_route, "general")

    # Retrieval works offline (keyword fallback) and is always disclosure-filtered.
    chunks = KnowledgeRetriever().retrieve(
        prompt, namespace=namespace, top_k=top_k, context=context
    )
    evidence = "\n".join(c.get("text", "") for c in chunks)

    if not settings.ENABLE_AI_ENGINE:
        return RagResult(partial={}, used_ai=False, chunks=chunks)

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
        logger.exception("RAG generation failed; returning deterministic-only result")
        return RagResult(partial={}, used_ai=False, chunks=chunks)


def generate_result_partial(**kwargs) -> dict:
    """Convenience wrapper returning just the safe partial dict."""
    return run_rag(**kwargs).partial
