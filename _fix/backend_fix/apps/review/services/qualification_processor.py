"""
Qualification processor — PHASE 2 / v4.0.1 FINAL FORM.

When a visitor finishes the qualification questions, this turns their answers into a
scored, routed result, creates a **real Lead**, reveals the client page (reveal ①), and
returns the result — **including the freshly minted client-page capability token and the
resulting journey state** — to the public site.

╔══════════════════════════════════════════════════════════════════════════════╗
║ v4.0   RESPONSE-SHAPE FIX  — return capability_token + journey_state             ║
║ v4.0.1 HANG-PROOF FIX      — never block the token response on AI work           ║
║                                                                                ║
║ Root cause of the stuck /review/preparing page in production (AI flags ON):     ║
║   qualify ran, INSIDE the request, (a) the Diagnosis agent (OpenAI embed +       ║
║   Pinecone query + a Claude call) via ResultGenerator AND (b) a second Claude     ║
║   call for the Concierge warm-up — with no timeouts, behind gunicorn --timeout   ║
║   120. When that combined work was slow, the worker was killed and the browser   ║
║   never received the token, so /review/preparing spun forever.                   ║
║                                                                                ║
║ This version makes the token the FIRST thing produced and guarantees it is       ║
║ returned regardless of AI latency:                                              ║
║   1. Score + route + create the Lead (fast, deterministic).                      ║
║   2. Mint the client-page token IMMEDIATELY (reveal ①) — before any AI.          ║
║   3. Build + persist the result page with a bounded AI enrichment that can        ║
║      never delay the token (the AI clients now carry hard timeouts; and the       ║
║      whole enrichment is wrapped so any failure is swallowed). If it is slow/off, ║
║      the deterministic result page is persisted and the /c/[token] page still     ║
║      renders — it regenerates on demand if needed.                                ║
║   4. The synchronous Concierge warm-up is REMOVED from the request path (it was   ║
║      pure priming and added a second blocking Claude call). The Concierge still   ║
║      answers live in the review/portal chat, unchanged.                           ║
║                                                                                ║
║ The response includes BOTH snake_case and camelCase keys so the public site's    ║
║ contract can never drift again.                                                  ║
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


# ── Result container (Phase 1 shape + v4.0 journey fields) ───────────────────
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
        Serialize for the public API. Returns BOTH snake_case (legacy / other consumers)
        and camelCase (the v3.0 public site reads these) keys so neither side can drift
        into a casing mismatch again.
        """
        breakdown = self.breakdown
        total = self.total
        return {
            # ── legacy snake_case shape ──────────────────────────────────────
            "lead_id": self.lead_id,
            "lead_is_placeholder": self.lead_is_placeholder,
            "score": {"breakdown": breakdown, "total": total},
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

    Robust — always returns a usable token when a Lead exists:
      1. Advance DIAGNOSED → CLIENT_PAGE via ``reveal_client_page`` and read the token
         off the returned ``AdvanceResult.reveal`` (normal path; also covers idempotent
         no-op retries, where ``advance`` still recomputes the reveal).
      2. If that yields no token (raised / unexpected), mint a client-page token directly
         from the lead via ``reveal_for_state``.
    Never raises.
    """
    from apps.journey.models import JourneyState

    token: str | None = None
    state: str | None = None

    try:
        from apps.journey.services.advance import reveal_client_page

        result = reveal_client_page(lead, meta={"source": "qualification"})
        state = getattr(result, "to_state", None) or state
        reveal = getattr(result, "reveal", None) or {}
        token = reveal.get("capability_token")
    except Exception:  # noqa: BLE001 - journey reveal must not block qualification
        logger.exception("journey reveal_client_page failed for lead %s", getattr(lead, "id", "?"))

    if not token:
        try:
            from apps.journey.services.reveal import reveal_for_state

            current = getattr(lead, "journey_state", None) or JourneyState.ARRIVED
            reveal = reveal_for_state(lead, JourneyState.CLIENT_PAGE) or reveal_for_state(lead, current)
            if reveal:
                token = reveal.get("capability_token") or token
                state = reveal.get("state") or state
        except Exception:  # noqa: BLE001
            logger.exception("client-page token fallback mint failed for lead %s", getattr(lead, "id", "?"))

    if not state:
        state = getattr(lead, "journey_state", None) or JourneyState.CLIENT_PAGE

    return token, state


def _build_result_page_now(lead_id: str) -> None:
    """
    Build + persist the personalized result page for ``lead_id`` (used by the background
    worker below). Re-fetches the lead so it is safe to run off the request thread. The
    AI clients carry hard timeouts; any failure is swallowed and logged.
    """
    try:
        import django

        # Ensure a usable DB connection on this thread; close it when done so we don't
        # leak connections from the pool.
        from django.db import close_old_connections

        close_old_connections()
        from apps.leads.models import Lead
        from apps.result_page.services.result_generator import ResultGenerator

        lead = Lead.objects.filter(id=lead_id).first()
        if lead is None:
            return
        ResultGenerator().generate_for_lead(lead)
    except Exception:  # noqa: BLE001 - background enrichment must never surface
        logger.exception("Background result-page generation failed for lead %s", lead_id)
    finally:
        try:
            from django.db import close_old_connections

            close_old_connections()
        except Exception:  # noqa: BLE001
            pass


def _kick_off_result_page(lead) -> str:
    """
    Start result-page generation WITHOUT blocking the qualify response.

    Preferred path: hand it to Celery (when ENABLE_CELERY is on). Otherwise run it in a
    daemon background thread so the HTTP response returns immediately with the token. The
    /c/[token] page regenerates the result page on demand if the background build hasn't
    finished yet, so nothing user-visible depends on this completing before the response.

    Returns a synchronous, deterministic ``next_step`` for the response body (never waits
    on the model).
    """
    lead_id = str(lead.id)

    # Try Celery first (non-blocking, durable) if the project wired a task + it's enabled.
    try:
        from django.conf import settings

        if getattr(settings, "ENABLE_CELERY", False):
            try:
                from apps.result_page.tasks import generate_result_page_task  # optional

                generate_result_page_task.delay(lead_id)
                return _sync_next_step(lead)
            except Exception:  # noqa: BLE001 - no task module / broker: fall through to thread
                logger.debug("Celery result-page task unavailable; using background thread.")
    except Exception:  # noqa: BLE001
        pass

    # Fallback: daemon thread. Does not block the response; errors are swallowed inside.
    try:
        import threading

        threading.Thread(
            target=_build_result_page_now,
            args=(lead_id,),
            name=f"resultpage-{lead_id[:8]}",
            daemon=True,
        ).start()
    except Exception:  # noqa: BLE001 - if we somehow can't spawn, the /c page regenerates
        logger.exception("Failed to start background result-page thread for lead %s", lead_id)

    return _sync_next_step(lead)


def _sync_next_step(lead) -> str:
    """A fast, deterministic next-step for the response (no model call)."""
    if getattr(lead, "recommended_next_step", ""):
        return lead.recommended_next_step
    try:
        from apps.result_page.services.next_step_builder import build_next_step

        return build_next_step(tier=lead.tier, product_route=lead.product_route)
    except Exception:  # noqa: BLE001
        return ""


# ── Public entry point ───────────────────────────────────────────────────────
def process_qualification(session, answers: dict) -> QualificationResult:
    """
    Score + route a completed qualification, create the real Lead, MINT THE CLIENT-PAGE
    TOKEN FIRST, then build the result page (bounded, best-effort), and return the public
    result including ``capability_token`` + ``journey_state``.
    """
    # ── 1) Score + route (authoritative, deterministic, fast) ────────────────
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

    # ── 2) Create (or update) the REAL lead (fast, deterministic) ────────────
    from apps.leads.services.lead_creator import LeadCreator

    lead = LeadCreator.create_from_review(
        session,
        answers=answers,
        score_breakdown=breakdown,
        score_total=total,
        tier=tier,
        product_route=product_route,
        license_pathway=license_pathway,
    )

    try:
        session.placeholder_lead_id = lead.id
        session.save(update_fields=["placeholder_lead_id", "updated_at"])
    except Exception:  # noqa: BLE001 - field is optional / best-effort
        pass

    # ── 3) MINT THE CLIENT-PAGE TOKEN IMMEDIATELY (reveal ①) ─────────────────
    # This is the critical fix: the token exists BEFORE any AI work, so the response can
    # always carry it even if the (bounded) result generation below is slow or fails.
    capability_token, journey_state = _client_page_token_for(lead)
    if not capability_token:
        logger.warning(
            "No client-page capability token could be minted for lead %s; the public "
            "site will fall back to polling the journey endpoint.",
            lead.id,
        )

    # ── 4) Kick off result-page generation OFF the request path ──────────────
    # The AI-heavy result page (Diagnosis agent → embed + Pinecone + Claude) is built in a
    # background thread (or Celery when enabled) so it can NEVER delay the qualify response.
    # We return a fast deterministic next_step now; the /c/[token] page shows the enriched
    # page once it's ready (and regenerates on demand if the background build lags).
    next_step = _kick_off_result_page(lead)

    # NOTE (v4.0.1): the synchronous Concierge "warm-up" Claude call that used to run here
    # has been REMOVED from the request path. It was best-effort priming only and added a
    # second blocking model call to the critical qualify path. The Concierge still answers
    # live in the review + portal chat (unchanged); nothing user-visible is lost.

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
