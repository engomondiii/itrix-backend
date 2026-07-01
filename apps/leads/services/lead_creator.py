"""
Lead creator.

The single entry point that turns a completed, scored, routed review into a real
``Lead`` (plus its initial ``submission`` activity). Called by the upgraded
``review.services.qualification_processor`` in Phase 2.

It also derives the human-readable industry / role / pain / stack from the Q1–Q9
answers (using the same option vocabulary as the frontend), computes the SLA response
deadline from the tier, sets exclusivity flags, and generates the internal bottleneck
summary. Lead creation is idempotent per review session: if a lead already exists for
the session it is updated rather than duplicated.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from apps.leads.models import Lead, LeadActivity
from apps.leads.services.exclusive_flag_handler import evaluate_exclusive_flag
from apps.leads.services.lead_summary_generator import generate_lead_summary
from apps.routing.services.routing_rules import multi, single
from apps.scoring.services.tier_classifier import TIER_RESPONSE_HOURS

logger = logging.getLogger("itrix")

# ── Answer-vocabulary → human label maps (mirror itrix-web review config) ────
_ORG_LABEL = {
    "hardware_chip": "Hardware / chip / accelerator",
    "cloud_infra": "Cloud or infrastructure provider",
    "enterprise_rd": "Enterprise R&D / engineering",
    "research": "Research institution",
    "individual": "Individual / independent",
}
_ROLE_LABEL = {
    "decision_maker": "Decision maker",
    "influencer": "Influencer",
    "evaluator": "Evaluator",
    "curious": "Personal interest",
}
_PAIN_LABEL = {
    "cost": "Cost",
    "speed": "Speed",
    "energy": "Energy",
    "stability_accuracy": "Stability & accuracy",
    "memory_data_movement": "Memory & data movement",
    "hardware_utilization": "Hardware utilization",
    "architecture": "Architecture",
}
_WORKLOAD_LABEL = {
    "linear_algebra": "Dense / complex linear algebra",
    "conservation": "Conservation-law / transport dynamics",
    "state_observation": "State estimation with partial observation",
    "mixed": "Mixed structure",
    "unsure": "Unsure",
}
_STACK_LABEL = {
    "matlab_julia": "MATLAB / Julia",
    "python_scipy": "Python / SciPy / NumPy",
    "r_sas": "R / SAS",
    "simulink_modelica": "Simulink / Modelica",
    "cae": "CAE (ANSYS / Abaqus / COMSOL / OpenFOAM)",
    "ai_ml": "PyTorch / TensorFlow / JAX",
    "native": "C / C++ / Fortran / CUDA",
    "hardware": "Custom hardware / runtime",
    "other": "Other",
}
_COMMERCIAL_INTENT_LABEL = {
    "exclusive": "Exclusive / strategic",
    "non_exclusive": "Non-exclusive",
    "product_only": "Product use only",
    "unsure": "Unsure",
}
_TIMELINE_LABEL = {
    "now": "Already blocking",
    "quarter": "This quarter",
    "year": "Within a year",
    "exploring": "Just exploring",
}


def _primary_pain(answers: dict) -> str:
    pressures = multi(answers.get("Q2"))
    for p in pressures:
        if p in _PAIN_LABEL:
            return _PAIN_LABEL[p]
    return ""


def _stack(answers: dict) -> list[str]:
    env = single(answers.get("Q1"))
    return [_STACK_LABEL.get(env, env)] if env else []


class LeadCreator:
    @staticmethod
    def create_from_review(
        session,
        *,
        answers: dict,
        score_breakdown: dict,
        score_total: int,
        tier: int,
        product_route: str,
        license_pathway: str | None,
        recommended_next_step: str = "",
    ) -> Lead:
        """Create (or update) the Lead for a completed review session."""
        exclusivity = evaluate_exclusive_flag(
            commercial_path=license_pathway, answers=answers, tier=tier
        )

        summary = generate_lead_summary(
            prompt=getattr(session, "prompt", "") or "",
            pressures=getattr(session, "pressure_areas", []) or [],
            product_route=product_route,
            tier=tier,
        )

        sla_hours = TIER_RESPONSE_HOURS.get(tier)
        sla_due = timezone.now() + timedelta(hours=sla_hours) if sla_hours else None

        fields = dict(
            client_id=getattr(session, "client_id", "") or "",
            visitor_name="",
            company="",
            email="",
            industry=_ORG_LABEL.get(single(answers.get("Q6")), ""),
            role=_ROLE_LABEL.get(single(answers.get("Q7")), ""),
            product_route=product_route if product_route in dict(Lead._meta.get_field("product_route").choices) else "general",
            commercial_path=(license_pathway or "none"),
            special_rights=exclusivity.special_rights,
            compute_bottleneck=summary,
            primary_pain=_primary_pain(answers),
            workload_type=_WORKLOAD_LABEL.get(single(answers.get("Q3")), ""),
            current_stack=_stack(answers),
            commercial_intent=_COMMERCIAL_INTENT_LABEL.get(single(answers.get("Q9")), ""),
            timeline=_TIMELINE_LABEL.get(single(answers.get("Q4")), ""),
            score=score_total,
            tier=tier,
            score_breakdown=score_breakdown,
            recommended_next_step=recommended_next_step,
            human_handoff_trigger=exclusivity.requires_human_review,
            qualification=answers,
            sla_response_due_at=sla_due,
            journey_state="IN_REVIEW",
        )

        existing = Lead.objects.filter(review_session=session).first()
        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            existing.save()
            lead = existing
            created = False
        else:
            lead = Lead.objects.create(review_session=session, **fields)
            created = True

        if created:
            LeadActivity.objects.create(
                lead=lead,
                type=LeadActivity.ActivityType.SUBMISSION,
                label=f"Lead created from review — Tier {tier}, score {score_total}/100.",
                meta={"product_route": product_route, "license_pathway": license_pathway},
            )

        # ── v4.0: advance the journey to DIAGNOSED (value delivered) ─────────
        # Deterministic + audited; the result page is the delivered value. This is
        # best-effort so lead creation never fails on a journey hiccup.
        try:
            from apps.journey.services.advance import mark_diagnosed

            mark_diagnosed(lead, meta={"review_session": str(session.id)})
        except Exception:  # noqa: BLE001 - journey advance must not block lead creation
            logger.exception("journey advance to DIAGNOSED failed for lead %s", lead.id)

        logger.info(
            "Lead %s for review %s (tier=%s score=%s route=%s)",
            "created" if created else "updated",
            session.id,
            tier,
            score_total,
            product_route,
        )
        return lead


def create_lead_from_review(session, **kwargs) -> Lead:
    """Module-level convenience wrapper."""
    return LeadCreator.create_from_review(session, **kwargs)
