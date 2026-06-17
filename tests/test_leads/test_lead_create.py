"""Lead creation tests — LeadCreator maps a review into a real Lead."""

from __future__ import annotations

import pytest

from apps.leads.models import Lead, LeadActivity
from apps.leads.services.lead_creator import LeadCreator
from apps.scoring.services.scorer import LeadScorer
from apps.routing.services.product_router import route_product
from apps.routing.services.license_router import route_license
from tests.factories.review_factory import ReviewSessionFactory
from tests.factories.scoring_factory import EXECUTION_ANSWERS

pytestmark = pytest.mark.django_db


def _create(session, answers):
    score = LeadScorer.score(answers)
    return LeadCreator.create_from_review(
        session,
        answers=answers,
        score_breakdown=score.breakdown,
        score_total=score.total,
        tier=score.tier,
        product_route=route_product(answers),
        license_pathway=route_license(answers),
    )


def test_creates_lead_with_scoring_and_routing():
    session = ReviewSessionFactory()
    lead = _create(session, EXECUTION_ANSWERS)
    assert isinstance(lead, Lead)
    assert lead.tier == 1
    assert lead.product_route == "alpha_core"
    assert lead.commercial_path == "strategic"
    assert lead.score >= 80


def test_creates_submission_activity():
    session = ReviewSessionFactory()
    lead = _create(session, EXECUTION_ANSWERS)
    acts = LeadActivity.objects.filter(lead=lead, type=LeadActivity.ActivityType.SUBMISSION)
    assert acts.exists()


def test_human_handoff_flag_for_tier1_exclusive():
    session = ReviewSessionFactory()
    lead = _create(session, EXECUTION_ANSWERS)
    assert lead.human_handoff_trigger is True


def test_idempotent_per_review_session():
    session = ReviewSessionFactory()
    lead1 = _create(session, EXECUTION_ANSWERS)
    lead2 = _create(session, EXECUTION_ANSWERS)
    assert lead1.id == lead2.id
    assert Lead.objects.filter(review_session=session).count() == 1


def test_sla_due_set_for_tier1():
    session = ReviewSessionFactory()
    lead = _create(session, EXECUTION_ANSWERS)
    assert lead.sla_response_due_at is not None


def test_maps_human_readable_industry_and_role():
    session = ReviewSessionFactory()
    lead = _create(session, EXECUTION_ANSWERS)
    assert lead.industry == "Hardware / chip / accelerator"
    assert lead.role == "Decision maker"


def test_display_properties():
    session = ReviewSessionFactory()
    lead = _create(session, EXECUTION_ANSWERS)
    assert lead.product_route_display == "ALPHA Core"
    assert lead.commercial_path_display == "Strategic"
