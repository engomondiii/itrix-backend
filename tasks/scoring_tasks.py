"""
Celery tasks for scoring.

Wrapper around the lead scorer for any future async re-scoring needs. Eager when
``ENABLE_CELERY`` is False. Scoring in the live flow runs inline in the review pipeline;
this task exists for batch/re-scoring scenarios.
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger("itrix")


@shared_task(name="scoring.score_answers")
def score_answers_task(answers: dict) -> dict:
    from apps.scoring.services.scorer import score_answers

    return score_answers(answers).to_dict()


@shared_task(name="scoring.rescore_lead")
def rescore_lead_task(lead_id: str) -> dict:
    from apps.leads.models import Lead
    from apps.scoring.services.scorer import score_answers
    from apps.scoring.services.tier_classifier import classify_tier

    lead = Lead.objects.filter(pk=lead_id).first()
    if not lead:
        return {"ok": False, "error": f"No lead {lead_id}"}
    result = score_answers(lead.qualification or {})
    lead.score = result.total
    lead.tier = classify_tier(result.total)
    lead.score_breakdown = result.breakdown
    lead.save(update_fields=["score", "tier", "score_breakdown", "updated_at"])
    return {"ok": True, "lead_id": str(lead.id), **result.to_dict()}
