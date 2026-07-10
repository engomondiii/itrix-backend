"""
Result generator.

Composes the full personalized result page for a lead from the eight section builders, then
**enriches** it with the AI/RAG partial when the engine is on. Deterministic builders are the
source of truth for structure and safety; the AI may override the narrative fields
(problemMirror, alphaFitSummary, diagnosis, kpiPreview, recommendedNextStep) but only after
passing the hallucination guard inside the RAG pipeline.

The result is persisted as a ``ResultPage`` (one per lead) and returned with a small report
(used_ai, chunk_count, guard activity) for the generation log.

This module is imported lazily by ai_engine.views to avoid an import cycle.
"""

from __future__ import annotations

import logging
import threading

from apps.leads.models import (
    COMMERCIAL_PATH_DISPLAY,
    PRODUCT_ROUTE_DISPLAY,
    Lead,
)
from apps.result_page.models import ResultPage
from apps.result_page.services.alpha_fit_builder import build_alpha_fit_summary
from apps.result_page.services.diagnosis_table_builder import build_diagnosis
from apps.result_page.services.kpi_preview_builder import build_kpi_preview
from apps.result_page.services.license_path_explainer import license_display
from apps.result_page.services.next_step_builder import build_next_step
from apps.result_page.services.problem_mirror_builder import build_problem_mirror
from apps.result_page.services.product_route_explainer import primary_technologies
from apps.result_page.services.proof_preview_builder import build_proof_preview

logger = logging.getLogger("itrix")


class _SkipAIEnrichment(Exception):
    """Internal sentinel: build the result page deterministically (no model call)."""


class ResultGenerator:
    def generate_for_lead(
        self, lead: Lead, *, context: str = "public", use_ai: bool = True
    ) -> tuple[ResultPage, dict]:
        """
        Build, persist, and return the result page for ``lead`` plus a report dict.

        ``use_ai`` gates the (slow) Diagnosis-agent / RAG enrichment. Background callers
        pass ``use_ai=True`` (default) to produce the AI-enriched page. The synchronous
        client-page GET path passes ``use_ai=False`` so it can persist a deterministic
        page INSTANTLY and never block on a live model call (the background build from
        qualification supplies the enriched version).
        """
        product_route = lead.product_route  # canonical code
        commercial_path = lead.commercial_path  # canonical code
        tier = lead.tier
        pressures = (
            lead.review_session.pressure_areas
            if lead.review_session and lead.review_session.pressure_areas
            else []
        )
        prompt = lead.review_session.prompt if lead.review_session else ""

        # ── Deterministic sections (always built) ────────────────────────────
        sections = {
            "problemMirror": build_problem_mirror(
                prompt=prompt, pressures=pressures, product_route=product_route
            ),
            "diagnosis": build_diagnosis(pressures=pressures),
            "alphaFitSummary": build_alpha_fit_summary(product_route=product_route, tier=tier),
            "kpiPreview": build_kpi_preview(product_route=product_route),
            "proofPreview": build_proof_preview(
                product_route=product_route, tier=tier, context=context
            ),
            "recommendedNextStep": (
                lead.recommended_next_step
                or build_next_step(tier=tier, product_route=product_route)
            ),
        }

        # ── Optional Diagnosis-agent enrichment (v4.0) ───────────────────────
        # When ENABLE_AGENTS is on, the narrative is produced by the Diagnosis agent
        # through the agent runtime (records an AgentRun + applies governance). When it
        # is off, we fall back to the compatibility shim (run_rag), which itself keys on
        # ENABLE_AI_ENGINE — so with every flag off the page is fully deterministic,
        # exactly as it shipped. Either way we merge ONLY the narrative fields the agent
        # actually produced, keeping the deterministic builders as the source of truth.
        report = {"used_ai": False, "chunk_count": 0, "prohibited_removed": [], "quant_hedged": []}
        narrative_keys = ("problemMirror", "alphaFitSummary", "diagnosis", "kpiPreview", "recommendedNextStep")
        try:
            from django.conf import settings

            if not use_ai:
                # Deterministic-only build (fast, no model call). Used by the client-page
                # GET path so the page never blocks on AI.
                raise _SkipAIEnrichment()

            if getattr(settings, "ENABLE_AGENTS", False):
                from apps.agents.services.context import AgentContext
                from apps.agents.services.runtime import run_diagnosis

                agent_ctx = AgentContext(
                    lead_id=str(lead.id),
                    prompt=prompt,
                    pressures=list(pressures or []),
                    product_route=product_route,
                    license_pathway=commercial_path if commercial_path != "none" else None,
                    tier=tier,
                    context_label="result_page",
                    nda_signed=(context == "nda"),
                )
                out = run_diagnosis(agent_ctx)
                report["used_ai"] = out.used_ai
                report["chunk_count"] = len(out.chunk_ids)
                report["governance_status"] = out.governance_status
                # Only merge agent output that auto-approved (never surface held drafts).
                if out.governance_status == "auto_approved":
                    for key in narrative_keys:
                        if out.payload.get(key):
                            sections[key] = out.payload[key]
            else:
                from apps.ai_engine.services.rag_pipeline import run_rag

                rag = run_rag(
                    prompt=prompt,
                    product_route=product_route,
                    license_pathway=commercial_path if commercial_path != "none" else None,
                    tier=tier,
                    pressures=pressures,
                    context=context,
                )
                report["used_ai"] = rag.used_ai
                report["chunk_count"] = len(rag.chunks)
                for key in narrative_keys:
                    if rag.partial.get(key):
                        sections[key] = rag.partial[key]
        except _SkipAIEnrichment:
            # Intentional deterministic-only build (use_ai=False) — not an error.
            pass
        except Exception:  # noqa: BLE001
            logger.exception("Diagnosis enrichment failed; using deterministic sections only")

        # ── Persist (one ResultPage per lead) ────────────────────────────────
        defaults = dict(
            tier=tier,
            score_breakdown=lead.score_breakdown,
            product_route=PRODUCT_ROUTE_DISPLAY.get(product_route, "ALPHA Compute"),
            license_pathway=(license_display(commercial_path) or ""),
            primary_technologies=primary_technologies(product_route),
            problem_mirror=sections["problemMirror"],
            diagnosis=sections["diagnosis"],
            alpha_fit_summary=sections["alphaFitSummary"],
            kpi_preview=sections["kpiPreview"],
            proof_preview=sections["proofPreview"],
            recommended_next_step=sections["recommendedNextStep"],
            used_ai=report["used_ai"],
        )
        # NEVER let a deterministic build (use_ai=False) clobber an already AI-enriched
        # page (v4.0.6). The client-page GET writes a fast deterministic page; if the
        # background AI build already finished first, overwriting it here would drop the
        # rich narrative back to the stub and pin usedAi=False. So when this build is
        # deterministic and an AI page already exists, keep the AI page.
        if not report["used_ai"]:
            existing = ResultPage.objects.filter(lead=lead).first()
            if existing is not None and getattr(existing, "used_ai", False):
                return existing, report

        result_obj, _created = ResultPage.objects.update_or_create(lead=lead, defaults=defaults)

        # Keep the lead's stored next step in sync if it was empty.
        if not lead.recommended_next_step:
            lead.recommended_next_step = sections["recommendedNextStep"]
            lead.save(update_fields=["recommended_next_step", "updated_at"])

        return result_obj, report

    def build_client_page(self, lead: Lead, *, context: str = "public", nda_signed: bool = False) -> dict:
        """
        Assemble the CUSTOMIZED CLIENT PAGE payload (Phase 2): the persisted result page
        plus the embedded Pitch agent room. Served behind the client_page capability
        token by ResultPageClientView. The Pitch room degrades to a deterministic room
        when agents are off, so the page always has a pitch.
        """
        from apps.result_page.models import ResultPage
        from apps.result_page.serializers import ResultPageSerializer

        # HANG-PROOF (v4.0.4): the client-page GET must return FAST. Never run a live
        # model call on this path. If the AI-enriched ResultPage already exists (built in
        # the background from qualification), serve it. If it doesn't exist yet, build a
        # DETERMINISTIC page instantly (use_ai=False) so the visitor gets the page now; the
        # background build / a later load supplies the enriched narrative.
        result_obj = ResultPage.objects.filter(lead=lead).first()
        if result_obj is None:
            result_obj, _report = self.generate_for_lead(lead, context=context, use_ai=False)

        # AI ENRICHMENT WITHOUT CELERY (v4.0.6): the GET stays instant (we never call the
        # model on this path), but if the stored page is still deterministic and the agent
        # layer is enabled, kick the AI regeneration onto a background thread. It persists
        # the enriched ResultPage a few seconds later, so the next GET / the WS
        # clientpage.final shows usedAi=True with the rich narrative — no Celery worker and
        # no blocking the visitor. Guarded so only one build runs at a time per lead.
        try:
            from django.conf import settings

            if getattr(settings, "ENABLE_AGENTS", False) and not getattr(result_obj, "used_ai", False):
                self._enrich_in_background(lead, context=context)
        except Exception:  # noqa: BLE001 - enrichment scheduling must never break the GET
            logger.exception("Failed to schedule background enrichment for lead %s", lead.id)

        pitch = self._build_pitch(lead, context=context, nda_signed=nda_signed)
        data = ResultPageSerializer(result_obj).data
        data["pitch"] = pitch
        return data

    # In-process guard so a burst of GETs (page + chat + journey sockets all hit the API
    # at once) doesn't launch several concurrent model builds for the same lead.
    _enriching: set = set()
    _enriching_lock = threading.Lock()

    def _enrich_in_background(self, lead: Lead, *, context: str) -> None:
        """Spawn a daemon thread that builds + persists the AI-enriched page for ``lead``."""
        import threading

        lead_id = str(lead.id)

        # De-dupe: skip if a build for this lead is already in flight.
        with ResultGenerator._enriching_lock:
            if lead_id in ResultGenerator._enriching:
                return
            ResultGenerator._enriching.add(lead_id)

        def _run():
            from django.db import close_old_connections

            close_old_connections()
            try:
                fresh = Lead.objects.filter(id=lead_id).first()
                if fresh is not None:
                    self.generate_for_lead(fresh, context=context, use_ai=True)
                    logger.info("Background AI enrichment complete for lead %s", lead_id)
            except Exception:  # noqa: BLE001
                logger.exception("Background AI enrichment failed for lead %s", lead_id)
            finally:
                with ResultGenerator._enriching_lock:
                    ResultGenerator._enriching.discard(lead_id)
                close_old_connections()

        threading.Thread(target=_run, name=f"enrich-{lead_id[:8]}", daemon=True).start()

    def _build_pitch(self, lead: Lead, *, context: str, nda_signed: bool) -> dict:
        """
        Assemble the embedded Pitch room.

        HANG-PROOF (v4.0.4): this runs on the synchronous client-page GET path, so it uses
        the DETERMINISTIC pitch room (no live Claude call). The deterministic room is
        claim-safe and structurally identical; the visitor gets a fully-formed pitch
        instantly instead of waiting ~20s+ for the Pitch agent. (The governed Pitch agent
        still runs where latency is acceptable — e.g. background regeneration — but never
        blocks page delivery.)
        """
        try:
            from apps.agents.services.context import AgentContext
            from apps.agents.services.pitch import PitchAgent

            session = getattr(lead, "review_session", None)
            ctx = AgentContext(
                lead_id=str(lead.id),
                prompt=getattr(session, "prompt", "") or "",
                pressures=list(getattr(session, "pressure_areas", []) or []),
                product_route=lead.product_route,
                license_pathway=lead.commercial_path if lead.commercial_path != "none" else None,
                tier=lead.tier,
                context_label="pitch",
                nda_signed=nda_signed,
                extra={"commercial_intent": getattr(lead, "commercial_intent", "")},
            )
            return PitchAgent().run_fallback(ctx).payload
        except Exception:  # noqa: BLE001
            logger.exception("Pitch assembly failed for lead %s; omitting pitch room", lead.id)
            return {}


def generate_result_for_lead(lead: Lead, **kwargs):
    return ResultGenerator().generate_for_lead(lead, **kwargs)
