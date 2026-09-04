"""Authoritative review qualification and asynchronous My Review preparation.

Qualification remains deterministic. It creates/updates the Lead and starts review
generation, but it does **not** reveal a client page or mint a browser credential. The
browser remains on the question interface and polls the bound review-status endpoint. A
one-time review access code is issued only after a complete ResultPage is READY.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

from apps.routing.services.license_router import route_license as _route_license
from apps.routing.services.product_router import route_product as _route_product
from apps.routing.services.routing_rules import single as _single
from apps.scoring.services.score_weights import CATEGORY_WEIGHTS  # re-export
from apps.scoring.services.scorer import LeadScorer
from apps.scoring.services.tier_classifier import classify_with_label

logger = logging.getLogger("itrix")


def score_answers(answers: dict) -> tuple[dict[str, int], int]:
    result = LeadScorer.score(answers)
    return result.breakdown, result.total


def classify_tier(total: int) -> tuple[int, str]:
    return classify_with_label(total)


def route_product(answers: dict) -> str:
    return _route_product(answers)


def route_license(answers: dict) -> str | None:
    return _route_license(answers)


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
    generation_status: str = "pending"

    def to_public_dict(self) -> dict:
        """Customer-safe qualification acknowledgement.

        Scoring, tier, Lead ids, hidden routing and commercial-pathway decisions are
        internal orchestration state.  A public qualification endpoint must never expose
        them even if a BFF currently strips them, because the backend is the authority.
        """
        return {
            "accepted": True,
            "generationStatus": self.generation_status,
            "reviewReady": self.generation_status == "ready",
        }

    def to_internal_dict(self) -> dict:
        """Team/test representation for deterministic scoring and routing."""
        return {
            "lead_id": self.lead_id,
            "score": {"breakdown": self.breakdown, "total": self.total},
            "tier": self.tier,
            "tier_label": self.tier_label,
            "product_route": self.product_route,
            "license_pathway": self.license_pathway,
            "next_step": self.next_step,
            "reasons": self.reasons,
            "generation_status": self.generation_status,
        }


def _reasons(answers: dict, *, total: int, license_pathway: str | None) -> list[str]:
    # Internal scoring explanation only. Avoid commercial language based merely on score.
    reasons: list[str] = []
    org = _single(answers.get("Q6"))
    if org in ("hardware_chip", "cloud_infra"):
        reasons.append("The submitted workload context is relevant to infrastructure evaluation.")
    if total >= 80:
        reasons.append("The questionnaire contains enough signal to prepare a structured review.")
    return reasons


def _mark_failed(lead_id: str, exc: Exception | str) -> None:
    try:
        from apps.leads.models import Lead
        from apps.result_page.services.result_generator import ResultGenerator

        lead = Lead.objects.filter(id=lead_id).first()
        if lead is not None:
            ResultGenerator.mark_failed(lead, exc)
    except Exception:  # noqa: BLE001
        logger.exception("Could not persist failed review state for lead %s", lead_id)


def _build_result_page_now(lead_id: str, *, finalize_conversation: bool = False) -> None:
    from django.db import close_old_connections

    close_old_connections()
    try:
        from apps.leads.models import Lead
        from apps.result_page.services.result_generator import ResultGenerator

        lead = Lead.objects.filter(id=lead_id).first()
        if lead is None:
            return
        ResultGenerator().generate_for_lead(lead)
        if finalize_conversation:
            try:
                from apps.conversations.services.reveal_bridge import finalize_ready_review

                finalize_ready_review(lead)
            except Exception:  # noqa: BLE001
                logger.exception("Conversation review finalization failed for lead %s", lead_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Background result-page generation failed for lead %s", lead_id)
        _mark_failed(lead_id, exc)
    finally:
        close_old_connections()


def kick_off_result_page(lead, *, finalize_conversation: bool = False) -> None:
    """Start generation outside the request path. Status is persisted PENDING/READY/FAILED."""
    from apps.result_page.models import ResultPage

    ResultPage.objects.update_or_create(
        lead=lead,
        defaults={
            "generation_status": ResultPage.GenerationStatus.PENDING,
            "generation_error": "",
            "artifact_family": "my_review",
        },
    )
    lead_id = str(lead.id)
    try:
        from django.conf import settings

        if getattr(settings, "ENABLE_CELERY", False):
            from apps.result_page.tasks import generate_result_page_task

            generate_result_page_task.delay(lead_id, finalize_conversation=finalize_conversation)
            return
    except Exception:  # noqa: BLE001
        logger.debug("Celery review generation unavailable; falling back to background thread", exc_info=True)

    threading.Thread(
        target=_build_result_page_now,
        kwargs={"lead_id": lead_id, "finalize_conversation": finalize_conversation},
        name=f"resultpage-{lead_id[:8]}",
        daemon=True,
    ).start()


def _sync_next_step() -> str:
    return "Preparing your My Review. You can continue on this page; the review will only become available when it is complete."


def process_qualification(session, answers: dict) -> QualificationResult:
    score = LeadScorer.score(answers)
    breakdown, total, tier, tier_label = score.breakdown, score.total, score.tier, score.tier_label
    product_route = _route_product(answers)
    license_pathway = _route_license(answers)

    session.answers = answers
    session.score_breakdown = breakdown
    session.score_total = total
    session.tier = tier
    session.product_route = product_route
    session.license_pathway = license_pathway or ""
    session.status = session.Status.QUALIFIED
    session.save(
        update_fields=[
            "answers", "score_breakdown", "score_total", "tier",
            "product_route", "license_pathway", "status", "updated_at",
        ]
    )

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
    # A questionnaire submission earns a review, not a sales-stage promotion. Keep the
    # numbered journey at DIAGNOSED until the completed review is actually revealed.
    if getattr(lead, "journey_state", "") not in {"DIAGNOSED", "CLIENT_PAGE"}:
        lead.journey_state = "DIAGNOSED"
        lead.save(update_fields=["journey_state", "updated_at"])

    session.placeholder_lead_id = lead.id
    session.save(update_fields=["placeholder_lead_id", "updated_at"])

    kick_off_result_page(lead)

    logger.info(
        "Qualification accepted for review %s; My Review generation started for lead %s",
        session.id,
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
        next_step=_sync_next_step(),
        reasons=_reasons(answers, total=total, license_pathway=license_pathway),
        generation_status="pending",
    )
