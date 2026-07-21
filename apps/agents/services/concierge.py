"""
Concierge agent.

The conversational front door (review chat + client-page chat). It answers a visitor's
question within the claims discipline, retrieving disclosure-filtered public/controlled
knowledge and never requesting confidential detail before an NDA. In Phase 1 it is
scaffolded behind ENABLE_AGENTS: the AI path produces a governed reply; the
deterministic fallback returns a calm, safe holding message so the funnel never breaks.

── STREAMING (v4.0.3) ────────────────────────────────────────────────────────
``stream_reply(ctx)`` yields the reply as plain-text deltas so the client-page / review
chat can render token-by-token (like Claude). The streamed path asks the model for prose
(not JSON) so partial tokens are always human-readable; the realtime consumer runs the
final governed text through the prohibited-language post-check before it persists. When
the AI engine is off, ``stream_reply`` yields nothing and the consumer falls back to the
deterministic ``run_fallback`` reply.
"""

from __future__ import annotations

import logging
from typing import Iterator

from apps.agents.services.base import BaseAgent
from apps.agents.services.context import AgentContext
from apps.agents.services.output_contract import AgentOutput

logger = logging.getLogger("itrix")

_CONCIERGE_INSTRUCTION = (
    "You are the itriX assessment concierge. Answer the visitor's question clearly and "
    "calmly, strictly within the claims discipline: no benchmark numbers, no guaranteed "
    "improvements, no competitor comparisons, and never request confidential technical "
    "detail before an NDA. Prefer 'may', 'potential', 'evaluated'. Respond ONLY with a "
    'JSON object: {"reply": string, "suggestNda": boolean}.'
)

# Streamed variant: prose only, so every partial token is readable as it arrives.
_CONCIERGE_STREAM_INSTRUCTION = (
    "You are the itriX assessment concierge. Answer the visitor's question clearly and "
    "calmly, strictly within the claims discipline: no benchmark numbers, no guaranteed "
    "improvements, no competitor comparisons, and never request confidential technical "
    "detail before an NDA. Prefer 'may', 'potential', 'evaluated'. Reply in plain, warm "
    "prose (no JSON, no markdown headings). Keep it concise — a few sentences."
)

_FALLBACK_REPLY = (
    "Thanks — I can help with that. I can share what iTrix does and why in general "
    "terms, which product may fit first, and what an evaluation could measure. For "
    "anything workload-specific, we keep it to non-confidential descriptions until an "
    "NDA is in place."
)

_ROUTE_TO_NAMESPACE = {
    "alpha_compute": "alpha-compute",
    "alpha_core": "alpha-core",
    "both": "alpha-compute",
    "general": "general",
}


class ConciergeAgent(BaseAgent):
    key = "concierge"
    name = "Concierge agent"
    default_claim_level = 1  # conversational, qualitative — auto-approves at default

    def _namespace(self, ctx: AgentContext) -> str:
        return _ROUTE_TO_NAMESPACE.get(ctx.product_route, "general")

    def _retrieval_context(self, ctx: AgentContext) -> str:
        """SECURITY INVARIANT 2 — the plane sets the ceiling, not the display label."""
        return ctx.retrieval_context

    def _question(self, ctx: AgentContext) -> str:
        return (ctx.extra or {}).get("message", "") or ctx.prompt

    def run_ai(self, ctx: AgentContext) -> AgentOutput:
        from apps.ai_engine.services.claude_client import AIEngineDisabled, ClaudeClient
        from apps.ai_engine.services.knowledge_retriever import KnowledgeRetriever
        from apps.ai_engine.services.system_prompt_builder import build_system_prompt

        question = self._question(ctx)
        retrieval_context = self._retrieval_context(ctx)

        chunks = KnowledgeRetriever().retrieve(
            question, namespace=self._namespace(ctx), top_k=6, context=retrieval_context
        )
        try:
            system = build_system_prompt(
                product_route=ctx.product_route,
                license_pathway=ctx.license_pathway,
                tier=ctx.tier,
                pressures=ctx.pressures,
                chunks=chunks,
                context=retrieval_context,
            )
            user = f"Visitor question:\n{question}\n\n{_CONCIERGE_INSTRUCTION}"
            raw = ClaudeClient().complete(system=system, user=user, max_tokens=700)
        except AIEngineDisabled:
            return AgentOutput(payload={}, used_ai=False)

        reply, suggest_nda = self._parse_reply(raw)
        return AgentOutput(
            payload={"reply": reply, "suggestNda": suggest_nda},
            chunk_ids=[c.get("chunk_id", "") for c in chunks if c.get("chunk_id")],
            used_ai=True,
            claim_level=self.default_claim_level,
        )

    def stream_reply(self, ctx: AgentContext) -> Iterator[str]:
        """
        Yield the concierge reply as plain-text deltas, BOUND TO A PRE-FLIGHT ENVELOPE.

        ── STREAMING GOVERNANCE, PART 1 (Backend v6.0 §6.1) ──────────────────
        Before a single token is yielded, the turn is bound to a claim ceiling derived
        from the plane, the state and the retrieved chunks. A turn that would require
        LEVEL-4 OR LEVEL-5 APPROVAL DOES NOT STREAM AT ALL — this generator yields
        nothing and the caller sends the approved under-review wording immediately.

        Nothing about a high-risk claim is ever rendered provisionally. A level-5 claim
        that streams for two seconds and is then retracted has already been read.

        Part 2 (the token-level stream guard) is applied by the CONSUMER as it forwards
        each token, because only the consumer can actually halt the socket. Part 3
        (settle) runs on the completed message.

        Yields nothing when the AI engine is off/unavailable either, so the caller can
        fall back to the deterministic reply.
        """
        from apps.governance.services import stream_envelope

        envelope = stream_envelope.for_context(
            ctx, intended_claim_level=self.default_claim_level
        )
        if not envelope.may_stream:
            logger.info(
                "concierge: envelope refused streaming (%s); caller must send "
                "the approved under-review wording",
                envelope.reason,
            )
            return

        from apps.ai_engine.services.claude_client import AIEngineDisabled, ClaudeClient
        from apps.ai_engine.services.knowledge_retriever import KnowledgeRetriever
        from apps.ai_engine.services.system_prompt_builder import build_system_prompt

        question = self._question(ctx)
        retrieval_context = self._retrieval_context(ctx)
        try:
            chunks = KnowledgeRetriever().retrieve(
                question, namespace=self._namespace(ctx), top_k=6, context=retrieval_context
            )
            system = build_system_prompt(
                product_route=ctx.product_route,
                license_pathway=ctx.license_pathway,
                tier=ctx.tier,
                pressures=ctx.pressures,
                chunks=chunks,
                context=retrieval_context,
            )
            user = f"Visitor question:\n{question}\n\n{_CONCIERGE_STREAM_INSTRUCTION}"
            yield from ClaudeClient().stream(system=system, user=user, max_tokens=700)
        except AIEngineDisabled:
            return
        except Exception:  # noqa: BLE001 - streaming must never propagate
            logger.exception("Concierge stream_reply failed")
            return

    @staticmethod
    def _parse_reply(raw: str) -> tuple[str, bool]:
        import json

        text = (raw or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if "\n" in text:
                text = text.split("\n", 1)[1]
        try:
            data = json.loads(text)
            return str(data.get("reply", "")).strip() or _FALLBACK_REPLY, bool(data.get("suggestNda", False))
        except Exception:  # noqa: BLE001
            # Model returned prose — use it directly if it's plausibly safe text.
            return (text or _FALLBACK_REPLY), False

    @property
    def fallback_reply(self) -> str:
        return _FALLBACK_REPLY

    def run_fallback(self, ctx: AgentContext) -> AgentOutput:
        return AgentOutput(
            payload={"reply": _FALLBACK_REPLY, "suggestNda": False},
            used_ai=False,
            claim_level=0,
        )
