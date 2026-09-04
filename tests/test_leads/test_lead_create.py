"""Lead creation tests — LeadCreator maps a review into a real Lead."""

from __future__ import annotations

import pytest

from apps.clients.models import Client
from apps.leads.models import Lead, LeadActivity, TrustStatus
from apps.leads.services.lead_creator import LeadCreator
from apps.scoring.services.scorer import LeadScorer
from apps.routing.services.product_router import route_product
from apps.routing.services.license_router import route_license
from tests.factories.review_factory import ReviewSessionFactory, VisitorSessionFactory
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


def test_anonymous_visitor_acquisition_survives_review_to_lead_conversion():
    visitor = VisitorSessionFactory(
        source_channel="partner_referral",
        campaign_content="astop-evaluation",
        referral_or_intro="Introduced by an existing industry contact",
        problem_topic="controller decision fidelity",
        referrer="https://example.test/referral",
    )
    session = ReviewSessionFactory(visitor_session=visitor)

    lead = _create(session, EXECUTION_ANSWERS)

    assert lead.acquisition_context == {
        "source_channel": "partner_referral",
        "campaign_content": "astop-evaluation",
        "referral_or_intro": "Introduced by an existing industry contact",
        "problem_topic": "controller decision fidelity",
        "referrer": "https://example.test/referral",
        "visitor_session_id": str(visitor.id),
    }


def test_repeated_lead_creation_keeps_acquisition_context_idempotent():
    visitor = VisitorSessionFactory(
        source_channel="organic",
        campaign_content="prism-public-page",
        problem_topic="observation performance",
    )
    session = ReviewSessionFactory(visitor_session=visitor)

    first = _create(session, EXECUTION_ANSWERS)
    first_context = dict(first.acquisition_context)
    second = _create(session, EXECUTION_ANSWERS)

    assert second.id == first.id
    assert second.acquisition_context == first_context
    assert Lead.objects.filter(review_session=session).count() == 1


def test_existing_curated_acquisition_values_win_on_idempotent_rerun():
    visitor = VisitorSessionFactory(
        source_channel="organic",
        campaign_content="visitor-campaign",
        referral_or_intro="Visitor supplied intro",
        problem_topic="visitor problem",
        referrer="https://example.test/original",
    )
    session = ReviewSessionFactory(visitor_session=visitor)
    lead = _create(session, EXECUTION_ANSWERS)
    lead.acquisition_context = {
        "source_channel": "operator_curated",
        "campaign_content": "curated-campaign",
        "referral_or_intro": "Verified human-entered introduction note",
        "custom_note": "keep me",
        "problem_topic": "",
    }
    lead.save(update_fields=["acquisition_context", "updated_at"])

    visitor.source_channel = "paid"
    visitor.campaign_content = "changed-campaign"
    visitor.problem_topic = "new observed problem"
    visitor.referrer = "https://example.test/changed"
    visitor.save()

    rerun = _create(session, EXECUTION_ANSWERS)

    assert rerun.acquisition_context["source_channel"] == "operator_curated"
    assert rerun.acquisition_context["campaign_content"] == "curated-campaign"
    assert rerun.acquisition_context["referral_or_intro"] == "Verified human-entered introduction note"
    assert rerun.acquisition_context["custom_note"] == "keep me"
    assert rerun.acquisition_context["problem_topic"] == "new observed problem"
    assert rerun.acquisition_context["referrer"] == "https://example.test/changed"
    assert rerun.acquisition_context["visitor_session_id"] == str(visitor.id)


def test_anonymous_visitor_session_id_is_retained_without_copying_browser_client_id():
    visitor = VisitorSessionFactory(client_id="browser-stable-id")
    session = ReviewSessionFactory(visitor_session=visitor)

    lead = _create(session, EXECUTION_ANSWERS)

    assert lead.acquisition_context["visitor_session_id"] == str(visitor.id)
    assert "client_id" not in lead.acquisition_context


def test_acquisition_source_does_not_directly_assign_persona():
    visitor = VisitorSessionFactory(
        source_channel="partner_referral",
        referral_or_intro="Trusted introduction",
    )
    session = ReviewSessionFactory(visitor_session=visitor)

    lead = _create(session, EXECUTION_ANSWERS)

    assert lead.persona_id is None


def test_trusted_introduction_does_not_auto_authorize_or_verify():
    visitor = VisitorSessionFactory(
        source_channel="partner_referral",
        referral_or_intro="Trusted introduction",
    )
    session = ReviewSessionFactory(visitor_session=visitor)

    lead = _create(session, EXECUTION_ANSWERS)

    assert lead.acquisition_context["referral_or_intro"] == "Trusted introduction"
    assert lead.trust_status == TrustStatus.UNREVIEWED
    assert lead.persona_id is None
    assert not Client.objects.filter(lead=lead).exists()
