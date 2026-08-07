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
    "detail before an NDA. Prefer 'may', 'potential', 'evaluated'. A QUESTION ABOUT "
    "itriX ITSELF — what it is, what it sells, who is behind it, how pricing works — "
    "IS A FAIR QUESTION: answer it from the knowledge context instead of redirecting "
    "to the visitor's workload. Respond ONLY with a "
    'JSON object: {"reply": string, "suggestNda": boolean}.'
)

# Streamed variant: prose only, so every partial token is readable as it arrives.
_CONCIERGE_STREAM_INSTRUCTION = (
    "You are the itriX assessment concierge. Answer the visitor's question clearly and "
    "calmly, strictly within the claims discipline: no benchmark numbers, no guaranteed "
    "improvements, no competitor comparisons, and never request confidential technical "
    "detail before an NDA. Prefer 'may', 'potential', 'evaluated'. A QUESTION ABOUT "
    "itriX ITSELF — what it is, what it sells, who is behind it, how pricing works — "
    "IS A FAIR QUESTION: answer it from the knowledge context instead of redirecting "
    "to the visitor's workload. Reply in plain, warm "
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

    def _conversation_user_prompt(self, ctx: AgentContext, question: str, instruction: str) -> str:
        """
        Build the user prompt WITH conversation memory.

        The turn path passes prior turns, closed-state summaries and the real journey
        state through ``ctx.extra`` (``recent_turns``, ``closed_state_summaries``,
        ``journey_state``). We fold them into a budgeted, priority-ordered context via
        ``context_assembly.assemble`` so the model can see what has already been said —
        which is the whole reason it stops re-greeting and re-asking answered questions.

        When ``extra`` carries no history (a bare first turn, or a caller that has not
        been updated), this degrades to the previous single-turn prompt, so no path is
        left worse off than before.
        """
        extra = ctx.extra or {}
        recent = list(extra.get("recent_turns") or [])
        summaries = list(extra.get("closed_state_summaries") or [])
        journey_state = extra.get("journey_state") or ""
        # The reveal directive hands over a page that EXISTS; the contact directive
        # asks for the one thing needed to generate it. They are mutually exclusive
        # by construction — the reveal requires the address the ask is asking for —
        # and the reveal wins if a caller ever sets both.
        reveal_directive = self._reveal_directive(extra) or self._contact_directive(extra)

        if not recent and not summaries:
            # No memory available for this turn — original single-turn behaviour.
            return f"Visitor question:\n{question}\n\n{reveal_directive}{instruction}"

        try:
            from apps.conversations.services import context_assembly

            assembled = context_assembly.assemble(
                system_contract=(
                    "The following is the running transcript of one continuous "
                    "conversation with a visitor. Earlier turns are context you have "
                    "ALREADY seen — do not restart, re-introduce yourself, or re-ask "
                    "anything the visitor has already answered. Continue naturally from "
                    "where the conversation actually is."
                ),
                journey_state=str(journey_state or ""),
                disclosure_ceiling=ctx.disclosure_ceiling,
                current_turn=f"Visitor (current turn): {question}",
                recent_turns=recent,
                closed_state_summaries=summaries,
            )
            memory_block = assembled.text()
        except Exception:  # noqa: BLE001 - memory is additive; never break generation
            logger.debug("context assembly failed; using single-turn prompt")
            return f"Visitor question:\n{question}\n\n{reveal_directive}{instruction}"

        return (
            f"{memory_block}\n\n"
            f"Now respond to the visitor's current turn.\n\n{reveal_directive}{instruction}"
        )

    @staticmethod
    def _reveal_directive(extra: dict) -> str:
        """
        When a personalised page has just been generated for this visitor, tell the
        model to HAND IT OVER rather than promise a human will follow up.

        This is the fix for the "the Assessment Team will be in touch" ending: the
        model has no other way to know an instant page exists, so without this it does
        the generic-concierge thing and promises human follow-up — the opposite of the
        intended outcome. The link itself is also appended to the reply by the turn
        path as a transport-independent fallback; this directive makes the model's OWN
        words match that outcome.
        """
        reveal = extra.get("client_page_reveal") or {}
        if not reveal.get("revealed"):
            return ""
        url = reveal.get("url") or ""
        return (
            "IMPORTANT — A PERSONALISED itriX PAGE HAS JUST BEEN GENERATED FOR THIS "
            "VISITOR AND IS READY NOW. Your reply MUST hand it over warmly and directly: "
            "tell them their personalised page is ready and that they can open it now"
            + (f" at this link: {url}" if url else "")
            + ". Do NOT say the team will 'be in touch', do NOT say you will 'prepare a "
            "briefing', do NOT ask to 'close the intake', and do NOT promise any human "
            "follow-up — the page is the deliverable and it exists already. Keep it to a "
            "couple of warm sentences. Then STOP.\n\n"
            "DO NOT WRITE THE LINK YOURSELF, and do not repeat the URL inside a sentence. "
            "The link is appended for you, on its own line, after whatever you write. A URL "
            "written mid-sentence ends up flush against the following full stop, and because "
            "the token itself contains a period, that punctuation breaks the link for anyone "
            "who selects it by hand. Refer to it as 'your personalised page' in words and let "
            "the link stand alone below.\n\n"
        )

    @staticmethod
    def _contact_directive(extra: dict) -> str:
        """
        When the review is complete but no email address has been given, tell the
        model to ASK FOR ONE rather than close the conversation.

        This is the other half of the "the Assessment Team will be in touch" fix.
        ``_reveal_directive`` above only fires once the personalised page exists, and
        the page cannot exist until an address is given — so without this the model
        was never told to ask, and the conversation dead-ended at DIAGNOSED.

        WHETHER to ask is decided deterministically upstream, in
        ``conversations.services.contact_ask``. This only carries the instruction.
        """
        from apps.conversations.services import contact_ask

        return contact_ask.directive(extra.get("contact_ask") or {})

    def run_ai(self, ctx: AgentContext) -> AgentOutput:
        from apps.ai_engine.services.claude_client import AIEngineDisabled, ClaudeClient
        from apps.ai_engine.services.knowledge_retriever import KnowledgeRetriever
        from apps.ai_engine.services.system_prompt_builder import build_conversation_system_prompt

        question = self._question(ctx)
        retrieval_context = self._retrieval_context(ctx)

        # A question naming a person or company embeds nothing about the workloads
        # they are associated with, so it retrieves on generic similarity and finds
        # generic chunks. The expansion appends the relevant workload families; the
        # visitor's own words stay first and are never replaced.
        from apps.ai_engine.services import entity_context

        chunks = KnowledgeRetriever().retrieve(
            entity_context.expand_query(question),
            namespace=self._namespace(ctx),
            top_k=6,
            context=retrieval_context,
        )
        try:
            # CONVERSATIONAL, not result-page. The shared builder's default TASK tells
            # the model to produce a diagnosis for a result page, which is why an
            # ordinary question ("what is itriX?") came back reframed as bottleneck
            # talk or declined outright. Same brand core, same claims discipline,
            # same grounding — different job.
            system = build_conversation_system_prompt(
                product_route=ctx.product_route,
                license_pathway=ctx.license_pathway,
                tier=ctx.tier,
                pressures=ctx.pressures,
                chunks=chunks,
                context=retrieval_context,
                question=question,
            )
            user = self._conversation_user_prompt(ctx, question, _CONCIERGE_INSTRUCTION)
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
        from apps.ai_engine.services.system_prompt_builder import build_conversation_system_prompt

        question = self._question(ctx)
        retrieval_context = self._retrieval_context(ctx)
        try:
            chunks = KnowledgeRetriever().retrieve(
                question, namespace=self._namespace(ctx), top_k=6, context=retrieval_context
            )
            # CONVERSATIONAL, not result-page. The shared builder's default TASK tells
            # the model to produce a diagnosis for a result page, which is why an
            # ordinary question ("what is itriX?") came back reframed as bottleneck
            # talk or declined outright. Same brand core, same claims discipline,
            # same grounding — different job.
            system = build_conversation_system_prompt(
                product_route=ctx.product_route,
                license_pathway=ctx.license_pathway,
                tier=ctx.tier,
                pressures=ctx.pressures,
                chunks=chunks,
                context=retrieval_context,
                question=question,
            )
            user = self._conversation_user_prompt(ctx, question, _CONCIERGE_STREAM_INSTRUCTION)
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
