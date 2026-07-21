"""
Proposal agent (Backend v4 §2.2) — NDA / eval / PoC / LOI / term-sheet OUTLINES.

DRAFT ONLY, claim level L5 — ALWAYS routed to human approval (and a second approver),
and watermarked. It never emits a binding document; it emits a structured outline a human
finalizes. Because default_claim_level = 5, the runtime queues it and it can never
auto-deliver.
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

_WATERMARK = "DRAFT — for internal review only; not a binding offer."

_JSON = (
    "Respond ONLY with a JSON object: "
    '{"documentType": one of ["nda","evaluation","poc","loi","term_sheet"], '
    '"outline": [{"section": string, "content": string}], "openQuestions": [string]}. '
    "This is a DRAFT OUTLINE only — never binding language, never final numbers."
)


class ProposalAgent(BaseAgent):
    key = "proposal"
    name = "Proposal agent"
    default_claim_level = 5

    def run_ai(self, ctx: AgentContext) -> AgentOutput:
        from apps.ai_engine.services.claude_client import AIEngineDisabled, ClaudeClient
        from apps.ai_engine.services.system_prompt_builder import build_system_prompt

        doc_type = (ctx.extra or {}).get("document_type", "evaluation")
        try:
            system = build_system_prompt(
                product_route=ctx.product_route, license_pathway=ctx.license_pathway,
                tier=ctx.tier, pressures=ctx.pressures, chunks=[], context=ctx.retrieval_context,
            )
            raw = ClaudeClient().complete(system=system, user=f"Draft a {doc_type} OUTLINE for:\n{ctx.prompt}\n\n{_JSON}", max_tokens=1200)
        except AIEngineDisabled:
            return self.run_fallback(ctx)
        import json
        try:
            data = json.loads(raw.strip().strip("`"))
            data["watermark"] = _WATERMARK
            return AgentOutput(payload=data, used_ai=True, claim_level=self.default_claim_level)
        except Exception:  # noqa: BLE001
            return self.run_fallback(ctx)

    def run_fallback(self, ctx: AgentContext) -> AgentOutput:
        doc_type = (ctx.extra or {}).get("document_type", "evaluation")
        return AgentOutput(
            payload={
                "documentType": doc_type,
                "watermark": _WATERMARK,
                "outline": [
                    {"section": "Parties & purpose", "content": "Placeholder — to be completed by a human owner."},
                    {"section": "Scope", "content": "What the engagement covers (qualitative)."},
                    {"section": "Success criteria", "content": "How fit will be assessed."},
                    {"section": "Terms", "content": "Deferred to legal — no binding language in this draft."},
                ],
                "openQuestions": ["Confirm commercial path", "Confirm evaluation scope with the client"],
            },
            used_ai=False,
            claim_level=5,
        )
