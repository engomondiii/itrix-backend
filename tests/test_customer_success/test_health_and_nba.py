"""
Customer health and the customer-first guardrail
(Architecture §18.7, Backend v6.0 §Phase 2).

    1. blocking support issue open              -> support action is primary
    2. agreed outcome off plan                  -> outcome action is primary
    3. adoption below plan                      -> enablement action is primary
    4. negative trust signal                    -> human outreach is primary
    5. otherwise, and only if expansion_allowed -> commercial action eligible

    A commercial candidate ranked primary while any of conditions 1-4 hold is A DEFECT,
    NOT A JUDGEMENT CALL.

The property that makes this safe is that health NEVER RETURNS "STABLE" ON MISSING DATA.
"""

from __future__ import annotations

import pytest

from apps.customer_success.services import (
    feedback_pulse,
    health_calculator,
    outcome_tracker,
    support_router,
)
from apps.journey.services.gate import expansion_allowed

pytestmark = pytest.mark.django_db


def test_a_new_customer_with_no_signals_is_unknown_not_stable(paying_client):
    """
    THE FAILURE THIS CLOSES. A brand-new customer with an empty workspace would
    otherwise be classed healthy by default and immediately receive an expansion CTA.
    """
    assessment = health_calculator.calculate(paying_client)
    assert assessment.health == health_calculator.HEALTH_UNKNOWN
    assert assessment.permits_expansion is False


def test_unknown_health_refuses_expansion(paying_client):
    assert expansion_allowed(paying_client.lead) is False


def test_a_blocking_support_issue_is_critical(paying_client):
    support_router.route(paying_client, "Production is down and we are blocked")
    assert health_calculator.calculate(paying_client).health == health_calculator.HEALTH_CRITICAL


def test_a_blocking_support_issue_suppresses_expansion(paying_client):
    outcome_tracker.create(paying_client, title="Cut cost")
    support_router.route(paying_client, "Production is down and we are blocked")
    health_calculator.recompute(paying_client)
    paying_client.refresh_from_db()
    assert expansion_allowed(paying_client.lead) is False


def test_an_off_plan_outcome_marks_at_risk(paying_client):
    outcome = outcome_tracker.create(paying_client, title="Hit the target")
    outcome_tracker.set_status(outcome, "off_plan")
    assert health_calculator.calculate(paying_client).health == health_calculator.HEALTH_AT_RISK


def test_a_negative_pulse_marks_at_risk(paying_client):
    outcome_tracker.create(paying_client, title="Ship it")
    feedback_pulse.submit(paying_client, score=1, comment="Not working for us")
    assert health_calculator.calculate(paying_client).health == health_calculator.HEALTH_AT_RISK


def test_a_measured_healthy_customer_is_stable(paying_client):
    outcome = outcome_tracker.create(paying_client, title="Reduce latency")
    outcome_tracker.set_status(outcome, "on_plan")
    assessment = health_calculator.calculate(paying_client)
    assert assessment.health == health_calculator.HEALTH_STABLE
    assert assessment.permits_expansion is True


def test_expansion_requires_a_paid_state(paying_client):
    """States below 7 are pre-payment; there is nothing to expand yet."""
    lead = paying_client.lead
    lead.journey_state = "CLIENT_PAGE"
    lead.save(update_fields=["journey_state"])
    assert expansion_allowed(lead) is False


def test_the_assessment_explains_itself(paying_client):
    """The reason is shown to the OPERATOR — a suppression they cannot explain is noise."""
    support_router.route(paying_client, "We are blocked in production")
    assessment = health_calculator.calculate(paying_client)
    assert assessment.reasons
    assert "blocking support request" in " ".join(assessment.reasons)
