"""
Pitch agent (Backend v4 §2.2, §Phase 2).

Selects 1 of 9 pitch types for a lead/client and assembles a 5–7 "slide" pitch room,
structured along the Problemology arc (Problem → Secret → Solution → Product → Purpose →
Proof → Commercialization). The slides are rendered on the customized client page.

Like every agent it follows the BaseAgent contract: an AI path (retrieval + Claude,
governed) and a deterministic fallback that composes a safe, claims-disciplined room
from the lead's route/tier/pressures. With ENABLE_AGENTS off (or the engine unavailable)
the fallback produces the full room, so the client page always has a pitch.

The nine pitch types map to the nine Problemology cores so retrieval and narrative stay
coherent: problem · secret · solution · product · purpose · proof · buyer · objection ·
commercialization.
"""

from __future__ import annotations

import logging

from apps.agents.services.base import BaseAgent
from apps.agents.services.context import AgentContext
from apps.agents.services.output_contract import AgentOutput

logger = logging.getLogger("itrix")

# The nine pitch types (aligned to the nine Problemology cores).
PITCH_TYPES = (
    "problem",
    "secret",
    "solution",
    "product",
    "purpose",
    "proof",
    "buyer",
    "objection",
    "commercialization",
)

_ROUTE_TO_NAMESPACE = {
    "alpha_compute": "alpha-compute",
    "alpha_core": "alpha-core",
    "both": "alpha-compute",
    "general": "general",
}

_PITCH_JSON_INSTRUCTION = (
    "You are assembling a short pitch room of 5-7 slides for a technical buyer, following "
    "the Problemology arc (Problem → Secret → Solution → Product → Purpose → Proof → "
    "Commercialization). Stay strictly within the claims discipline: no benchmark numbers, "
    "no guaranteed improvements, no competitor comparisons. Respond ONLY with a JSON object: "
    '{"pitchType": one of ' + str(list(PITCH_TYPES)) + ', '
    '"slides": [{"core": string, "title": string, "body": string}], '
    '"headline": string}. Provide between 5 and 7 slides.'
)


def select_pitch_type(ctx: AgentContext) -> str:
    """
    Deterministic pitch-type selection from the lead's signals. Auditable, no LLM:
      * strong commercial intent / exclusivity → commercialization
      * tier 1–2 (high fit) → secret (lead with the differentiator)
      * cost/energy/speed pressure → problem (mirror the pain first)
      * otherwise → solution
    """
    intent = (ctx.extra or {}).get("commercial_intent", "") or ""
    if ctx.license_pathway in {"exclusive", "strategic"} or intent in {
        "field_licensing",
        "strategic_investment",
        "acquisition_partnership",
    }:
        return "commercialization"
    if ctx.tier in (1, 2):
        return "secret"
    pressures = {p.lower() for p in (ctx.pressures or [])}
    if pressures & {"cost", "energy", "speed", "memory_data_movement"}:
        return "problem"
    return "solution"



def resolve_persona_room(ctx: AgentContext, *, ceiling: str = "public") -> dict:
    """
    Resolve the persona-keyed pitch room for this context.

    Returns the generic room when the personas app is unavailable or nothing matched —
    never raises, because a missing registry must degrade to the safe generic pitch
    rather than failing the turn.
    """
    try:
        from apps.personas.services.pitch_room_resolver import GENERIC_ROOM, resolve_for_lead
        from apps.leads.models import Lead

        if not ctx.lead_id:
            return {**GENERIC_ROOM, "match_path": "generic", "persona_id": None,
                    "slides_withheld": 0}
        lead = Lead.objects.filter(id=ctx.lead_id).first()
        if lead is None:
            return {**GENERIC_ROOM, "match_path": "generic", "persona_id": None,
                    "slides_withheld": 0}
        example_key = (ctx.extra or {}).get("example_key", "")
        return resolve_for_lead(lead, ceiling=ceiling, example_key=example_key)
    except Exception:  # noqa: BLE001 - registry optional; never fail a pitch on it
        logger.debug("persona room resolution unavailable; using generic template")
        try:
            from apps.personas.services.pitch_room_resolver import GENERIC_ROOM

            return {**GENERIC_ROOM, "match_path": "generic", "persona_id": None,
                    "slides_withheld": 0}
        except Exception:  # noqa: BLE001
            return {"pitch_room_id": "PR-GENERIC-01", "title": "", "slides": [],
                    "match_path": "generic", "persona_id": None, "slides_withheld": 0}



def _blueprint_hint(persona_room: dict) -> str:
    """
    Turn the resolved room into guidance for the model.

    Passes the room's SLIDE STRUCTURE and framing, never the persona label. The model is
    told how to frame the argument; it is never told who it thinks it is talking to,
    because a model that knows the inferred identity will eventually say it out loud.
    """
    slides = persona_room.get("slides") or []
    if not slides:
        return ""
    lines = [
        "Use this approved slide structure as the shape of the brief. Adapt the wording "
        "to the visitor's own problem, keep every claim qualitative, and do NOT mention "
        "or imply any assumption about the visitor's company, department or role:",
    ]
    for slide in slides[:7]:
        title = (slide or {}).get("title", "")
        body = (slide or {}).get("body", "")
        lines.append(f"  - {title}: {body[:220]}")
    return "\n".join(lines) + "\n\n"


class PitchAgent(BaseAgent):
    key = "pitch"
    name = "Pitch agent"
    default_claim_level = 2  # qualitative pitch narrative — auto-approves at default

    def _namespace(self, ctx: AgentContext) -> str:
        return _ROUTE_TO_NAMESPACE.get(ctx.product_route, "general")

    def run_ai(self, ctx: AgentContext) -> AgentOutput:
        from apps.ai_engine.services.claude_client import AIEngineDisabled, ClaudeClient
        from apps.ai_engine.services.knowledge_retriever import KnowledgeRetriever
        from apps.ai_engine.services.system_prompt_builder import build_system_prompt

        pitch_type = select_pitch_type(ctx)
        # SECURITY INVARIANT 2 — derived from the identity plane, never from the
        # display label. A client_page label on the public plane is still public.
        retrieval_context = ctx.retrieval_context

        # ── v6.0: persona-aware template resolution ──────────────────────────
        # exact persona -> functional family -> generic. The chosen path is recorded on
        # the AgentRun so the cockpit can tell a tailored room from a fallback.
        #
        # PERSONALIZATION WITHOUT PROFILING: the resolved room changes the FRAMING and
        # the EMPHASIS. It never produces a sentence that names the match, the company,
        # the department or the score. persona_id and pitch_room_id are internal-only
        # (§10.5) and are stripped before any client-plane payload.
        persona_room = resolve_persona_room(ctx, ceiling=retrieval_context)
        chunks = KnowledgeRetriever().retrieve(
            ctx.prompt or pitch_type, namespace=self._namespace(ctx), top_k=8, context=retrieval_context
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
            blueprint = _blueprint_hint(persona_room)
            user = (
                f"Lead problem:\n{ctx.prompt}\n\nLead pitch type to lead with: {pitch_type}\n\n"
                f"{blueprint}"
                f"{_PITCH_JSON_INSTRUCTION}"
            )
            raw = ClaudeClient().complete(system=system, user=user, max_tokens=1400)
        except AIEngineDisabled:
            return self.run_fallback(ctx)

        payload = self._parse(raw, fallback_type=pitch_type)
        if not payload.get("slides"):
            return self.run_fallback(ctx)

        # Record WHICH resolution path produced this room. Internal-only: the cockpit
        # needs to tell a tailored room from a fallback, and without this they look
        # identical in the data.
        payload["_match_path"] = persona_room.get("match_path", "generic")
        payload["_persona_id"] = persona_room.get("persona_id")
        payload["_pitch_room_id"] = persona_room.get("pitch_room_id")

        return AgentOutput(
            payload=payload,
            chunk_ids=[c.get("chunk_id", "") for c in chunks if c.get("chunk_id")],
            used_ai=True,
            claim_level=self.default_claim_level,
        )

    @staticmethod
    def _parse(raw: str, *, fallback_type: str) -> dict:
        import json

        text = (raw or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if "\n" in text:
                text = text.split("\n", 1)[1]
        try:
            data = json.loads(text)
            slides = data.get("slides") or []
            clean_slides = [
                {"core": str(s.get("core", "")), "title": str(s.get("title", "")), "body": str(s.get("body", ""))}
                for s in slides
                if isinstance(s, dict)
            ]
            return {
                "pitchType": data.get("pitchType", fallback_type),
                "headline": str(data.get("headline", "")),
                "slides": clean_slides[:7],
            }
        except Exception:  # noqa: BLE001
            return {}

    def run_fallback(self, ctx: AgentContext) -> AgentOutput:
        """Deterministic, claims-disciplined 6-slide room built from the lead's signals."""
        pitch_type = select_pitch_type(ctx)
        route_label = {
            "alpha_compute": "ALPHA Compute",
            "alpha_core": "ALPHA Core",
            "both": "ALPHA Compute + Core",
        }.get(ctx.product_route, "ALPHA")

        slides = [
            {
                "core": "problem",
                "title": "The bottleneck you described",
                "body": (
                    "Your workload is constrained where it matters most. We start from the "
                    "specific pressure you named rather than a generic capability list."
                ),
            },
            {
                "core": "secret",
                "title": "Why this is usually hard",
                "body": (
                    "Most approaches trade one pressure for another. The underlying insight "
                    f"behind {route_label} is a different way of organizing the computation."
                ),
            },
            {
                "core": "solution",
                "title": f"How {route_label} approaches it",
                "body": (
                    "A qualitative fit description — where the approach may help and where an "
                    "evaluation would be the honest next step to confirm fit on your data."
                ),
            },
            {
                "core": "product",
                "title": "What you would actually work with",
                "body": (
                    f"{route_label} in the form that matches your stack and integration path, "
                    "described without commitments we haven't earned."
                ),
            },
            {
                "core": "purpose",
                "title": "Why we build it this way",
                "body": (
                    "Our intent is durable capability for hard computation, not a one-off "
                    "benchmark. That shapes how we evaluate and license."
                ),
            },
            {
                "core": "proof",
                "title": "What an evaluation would measure",
                "body": (
                    "A concrete, scoped assessment on representative work — the point at which "
                    "qualitative fit becomes evidence you can act on."
                ),
            },
        ]
        return AgentOutput(
            payload={
                "pitchType": pitch_type,
                "headline": f"{route_label}: from your bottleneck to a measurable next step",
                "slides": slides,
            },
            chunk_ids=[],
            used_ai=False,
            claim_level=0,
        )
