"""
Qualification processor — PHASE 2 / v4.0 FINAL FORM.

When a visitor finishes the qualification questions, this turns their answers into a
scored, routed result, creates a **real Lead**, generates the personalized result page,
advances the journey to reveal the client page (reveal ①), and returns the result —
**including the freshly minted client-page capability token and the resulting journey
state** — to the public site.

╔══════════════════════════════════════════════════════════════════════════════╗
║ v4.0 RESPONSE-SHAPE FIX                                                          ║
║                                                                                ║
║ The public site was upgraded to v3.0 and now REQUIRES two extra fields in the   ║
║ qualify response so it can hand the visitor off to the token-gated /c/[token]   ║
║ page:                                                                           ║
║     • capability_token — the client-page capability token (reveal ①)            ║
║     • journey_state    — the resulting journey state (e.g. CLIENT_PAGE)         ║
║                                                                                ║
║ Previously the token was minted as a side-effect of ``reveal_client_page`` but  ║
║ the return value was discarded and ``to_dict()`` had no field for it, so the    ║
║ token never reached the browser and the review dead-ended at /review/preparing. ║
║                                                                                ║
║ This version captures the ``AdvanceResult``, extracts the token + state, and    ║
║ includes them in the response. It is robust to:                                 ║
║   • the reveal being an idempotent no-op on retry (re-mints a fresh token),      ║
║   • the reveal raising (falls back to minting a token directly from the lead),   ║
║ so a valid client-page token is returned whenever a real Lead exists.            ║
║                                                                                ║
║ The legacy keys are unchanged; only additive fields are introduced, so any       ║
║ existing consumer keeps working.                                                ║
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


# ── Result container (same public shape as Phase 1 + v4.0 journey fields) ────
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
    # ── v4.0 additive fields (drive the /review/preparing → /c/[token] hand-off) ──
    capability_token: str | None = None
    journey_state: str | None = None

    def to_dict(self) -> dict:
        """
        Serialize for the public API. We return BOTH snake_case (legacy / other
        consumers) and camelCase (the v3.0 public site reads these) keys so neither
        side can drift into a casing mismatch again. The proxy may forward this
        verbatim and the browser will find the keys it expects.
        """
        breakdown = self.breakdown
        total = self.total
        return {
            # ── legacy snake_case shape (unchanged) ──────────────────────────
            "lead_id": self.lead_id,
            "lead_is_placeholder": self.lead_is_placeholder,
            "score": {
                "breakdown": breakdown,
                "total": total,
            },
            "tier": self.tier,
            "tier_label": self.tier_label,
            "product_route": self.product_route,
            "license_pathway": self.license_pathway,
            "next_step": self.next_step,
            "reasons": self.reasons,
            # ── v4.0 journey fields (snake_case) ─────────────────────────────
            "capability_token": self.capability_token,
            "journey_state": self.journey_state,
            # ── camelCase mirror (what the v3.0 public site reads directly) ──
            "leadId": self.lead_id,
            "leadIsPlaceholder": self.lead_is_placeholder,
            "totalScore": total,
            "scoreBreakdown": breakdown,
            "tierLabel": self.tier_label,
            "productRoute": self.product_route,
            "licensePathway": self.license_pathway,
            "nextStep": self.next_step,
            "capabilityToken": self.capability_token,
            "journeyState": self.journey_state,
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


def _client_page_token_for(lead) -> tuple[str | None, str | None]:
    """
    Return ``(capability_token, journey_state)`` for the lead's client-page reveal.

    Strategy (robust — always returns a usable token when a Lead exists):
      1. Advance DIAGNOSED → CLIENT_PAGE via ``reveal_client_page`` and read the token
         off the returned ``AdvanceResult.reveal``. This is the normal path.
      2. If the advance is an idempotent no-op (lead already at/after CLIENT_PAGE, e.g.
         a retry) the reveal descriptor is still recomputed by ``advance``, so the
         token is present — we use it.
      3. If the advance raises or yields no token for any reason, fall back to minting a
         client-page token directly from the lead id via ``reveal_for_state``.

    Never raises; returns ``(None, <state>)`` only if token minting is impossible.
    """
    from apps.journey.models import JourneyState

    token: str | None = None
    state: str | None = None

    # ── Path 1 + 2: advance (or idempotent no-op) and read the reveal token ──
    try:
        from apps.journey.services.advance import reveal_client_page

        result = reveal_client_page(lead, meta={"source": "qualification"})
        state = getattr(result, "to_state", None) or state
        reveal = getattr(result, "reveal", None) or {}
        token = reveal.get("capability_token")
    except Exception:  # noqa: BLE001 - journey reveal must not block qualification
        logger.exception("journey reveal_client_page failed for lead %s", getattr(lead, "id", "?"))

    # ── Path 3: defensive fallback — mint a client-page token from current state ──
    if not token:
        try:
            from apps.journey.services.reveal import reveal_for_state

            # Prefer the lead's current state; if it hasn't reached CLIENT_PAGE for any
            # reason, mint against CLIENT_PAGE explicitly so the hand-off still works.
            current = getattr(lead, "journey_state", None) or JourneyState.ARRIVED
            reveal = reveal_for_state(lead, JourneyState.CLIENT_PAGE) or reveal_for_state(lead, current)
            if reveal:
                token = reveal.get("capability_token") or token
                state = reveal.get("state") or state
        except Exception:  # noqa: BLE001
            logger.exception("client-page token fallback mint failed for lead %s", getattr(lead, "id", "?"))

    # Final state resolution (never leave it empty when we know the lead's state).
    if not state:
        state = getattr(lead, "journey_state", None) or JourneyState.CLIENT_PAGE

    return token, state


# ── Public entry point ───────────────────────────────────────────────────────
def process_qualification(session, answers: dict) -> QualificationResult:
    """
    Score + route a completed qualification, create the real Lead, generate its result
    page, reveal the client page, and return the public result — now including the
    client-page ``capability_token`` and the resulting ``journey_state`` so the public
    site can hand the visitor off to /c/[token].
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
    # the personalized page exists, reveal it AND CAPTURE the minted token + state so we
    # can return them to the public site. Best-effort — never blocks the response.
    capability_token, journey_state = _client_page_token_for(lead)

    if not capability_token:
        logger.warning(
            "No client-page capability token could be minted for lead %s; the public "
            "site will fall back to polling the journey endpoint.",
            lead.id,
        )

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
        "Qualification processed for review %s: total=%s tier=%s route=%s lead=%s state=%s token=%s",
        session.id,
        total,
        tier,
        product_route,
        lead.id,
        journey_state,
        "yes" if capability_token else "no",
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
        capability_token=capability_token,
        journey_state=journey_state,
    )
