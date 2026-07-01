"""
Qualification processor — PHASE 2 FINAL FORM.

When a visitor finishes the qualification questions, this turns their answers into a
scored, routed result, creates a **real Lead**, generates the personalized result page,
and returns the result to the public site.

╔══════════════════════════════════════════════════════════════════════════════╗
║ This is the Phase 2 upgrade of the Phase 1 "initial form".                      ║
║                                                                                ║
║ It now delegates to the dedicated apps:                                         ║
║   • apps.routing   — ProductRouter + LicenseRouter                              ║
║   • apps.scoring   — LeadScorer + tier_classifier                               ║
║   • apps.leads     — LeadCreator (creates the REAL Lead, returns its id)        ║
║   • apps.result_page — ResultGenerator (builds + persists the result page)      ║
║                                                                                ║
║ The PUBLIC RESPONSE SHAPE is identical to Phase 1's (same keys via              ║
║ ``QualificationResult.to_dict()``), so the frontend needs NO change. The only   ║
║ behavioural differences visitors/dashboard see: ``lead_id`` is now a real Lead  ║
║ id and ``lead_is_placeholder`` is False.                                        ║
║                                                                                ║
║ The legacy module-level helpers (score_answers, classify_tier, route_product,   ║
║ route_license, CATEGORY_WEIGHTS) are kept as thin re-exports over the new        ║
║ services so any existing imports/tests keep working.                            ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from apps.routing.services.license_router import route_license as _route_license
from apps.routing.services.product_router import route_product as _route_product
from apps.routing.services.routing_rules import single as _single
from apps.scoring.services.score_weights import CATEGORY_WEIGHTS  # re-export
from apps.scoring.services.scorer import LeadScorer
from apps.scoring.services.tier_classifier import classify_with_label

logger = logging.getLogger("itrix")


# ── Backwards-compatible helper re-exports ───────────────────────────────────
def score_answers(answers: dict) -> tuple[dict[str, int], int]:
    """Return (breakdown, total) — delegates to the scoring app."""
    result = LeadScorer.score(answers)
    return result.breakdown, result.total


def classify_tier(total: int) -> tuple[int, str]:
    """Return (tier, label) — delegates to the scoring app."""
    return classify_with_label(total)


def route_product(answers: dict) -> str:
    return _route_product(answers)


def route_license(answers: dict) -> str | None:
    return _route_license(answers)


# ── Result container (same public shape as Phase 1) ──────────────────────────
@dataclass
class QualificationResult:
    breakdown: dict[str, int]
    total: int
    tier: int
    tier_label: str
    product_route: str
    license_pathway: str | None
    lead_id: str
    lead_is_placeholder: bool = False
    next_step: str = ""
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "lead_id": self.lead_id,
            "lead_is_placeholder": self.lead_is_placeholder,
            "score": {
                "breakdown": self.breakdown,
                "total": self.total,
            },
            "tier": self.tier,
            "tier_label": self.tier_label,
            "product_route": self.product_route,
            "license_pathway": self.license_pathway,
            "next_step": self.next_step,
            "reasons": self.reasons,
        }


def _reasons(answers: dict, *, total: int, license_pathway: str | None) -> list[str]:
    reasons: list[str] = []
    org = _single(answers.get("Q6"))
    if org in ("hardware_chip", "cloud_infra"):
        reasons.append("High strategic fit for the target industries.")
    if total >= 80:
        reasons.append("Strong overall signal across fit, urgency, and intent.")
    if license_pathway:
        reasons.append("Expressed interest in licensing the underlying technology.")
    return reasons


# ── Public entry point ───────────────────────────────────────────────────────
def process_qualification(session, answers: dict) -> QualificationResult:
    """
    Score + route a completed qualification, create the real Lead, generate its result
    page, and return the public result.

    The return shape matches Phase 1 exactly (so the frontend is unchanged); ``lead_id``
    is now the real Lead id and ``lead_is_placeholder`` is False.
    """
    # ── Score + route (authoritative, via the dedicated apps) ────────────────
    score = LeadScorer.score(answers)
    breakdown, total, tier, tier_label = score.breakdown, score.total, score.tier, score.tier_label
    product_route = _route_product(answers)
    license_pathway = _route_license(answers)

    # ── Persist the computed result onto the review session ──────────────────
    session.answers = answers
    session.score_breakdown = breakdown
    session.score_total = total
    session.tier = tier
    session.product_route = product_route
    session.license_pathway = license_pathway or ""
    session.status = session.Status.QUALIFIED
    session.save(
        update_fields=[
            "answers",
            "score_breakdown",
            "score_total",
            "tier",
            "product_route",
            "license_pathway",
            "status",
            "updated_at",
        ]
    )

    # ── Create (or update) the REAL lead ─────────────────────────────────────
    from apps.leads.services.lead_creator import LeadCreator
    from apps.result_page.services.result_generator import ResultGenerator

    lead = LeadCreator.create_from_review(
        session,
        answers=answers,
        score_breakdown=breakdown,
        score_total=total,
        tier=tier,
        product_route=product_route,
        license_pathway=license_pathway,
    )

    # Keep the session's placeholder field pointing at the real lead for traceability.
    try:
        session.placeholder_lead_id = lead.id
        session.save(update_fields=["placeholder_lead_id", "updated_at"])
    except Exception:  # noqa: BLE001 - field is optional / best-effort
        pass

    # ── Generate + persist the personalized result page ──────────────────────
    next_step = ""
    try:
        result_obj, _report = ResultGenerator().generate_for_lead(lead)
        next_step = result_obj.recommended_next_step
    except Exception:  # noqa: BLE001 - never block qualification on result generation
        logger.exception("Result page generation failed during qualification for lead %s", lead.id)
        next_step = lead.recommended_next_step or ""

    # ── v4.0: advance the journey to reveal the client page (reveal ①) ───────
    # lead_creator already advanced the journey to DIAGNOSED (value delivered). Now that
    # the personalized page exists, reveal it. Best-effort — never blocks the response.
    try:
        from apps.journey.services.advance import reveal_client_page

        reveal_client_page(lead, meta={"review_session": str(session.id)})
    except Exception:  # noqa: BLE001 - journey reveal must not block qualification
        logger.exception("journey reveal_client_page failed for lead %s", lead.id)

    # ── v4.0: optionally warm up the Concierge agent (behind ENABLE_AGENTS) ──
    # This primes the review-chat agent for the visitor's opening context. It is a
    # no-op unless ENABLE_AGENTS is on, and it never affects the returned result.
    try:
        from django.conf import settings

        if getattr(settings, "ENABLE_AGENTS", False):
            from apps.agents.services.context import AgentContext
            from apps.agents.services.runtime import run_concierge

            run_concierge(
                AgentContext(
                    lead_id=str(lead.id),
                    prompt=getattr(session, "prompt", "") or "",
                    pressures=list(getattr(session, "pressure_areas", []) or []),
                    product_route=product_route,
                    license_pathway=license_pathway,
                    tier=tier,
                    context_label="review",
                    extra={"message": getattr(session, "prompt", "") or ""},
                )
            )
    except Exception:  # noqa: BLE001 - agent warm-up is best-effort
        logger.exception("Concierge warm-up failed for lead %s", lead.id)

    logger.info(
        "Qualification processed for review %s: total=%s tier=%s route=%s lead=%s",
        session.id,
        total,
        tier,
        product_route,
        lead.id,
    )

    return QualificationResult(
        breakdown=breakdown,
        total=total,
        tier=tier,
        tier_label=tier_label,
        product_route=product_route,
        license_pathway=license_pathway,
        lead_id=str(lead.id),
        lead_is_placeholder=False,
        next_step=next_step,
        reasons=_reasons(answers, total=total, license_pathway=license_pathway),
    )
