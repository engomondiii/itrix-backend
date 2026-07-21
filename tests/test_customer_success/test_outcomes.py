"""Outcome tracking (Playbook §12B) — these are the CUSTOMER's outcomes."""

from __future__ import annotations

import pytest

from apps.customer_success.models import OutcomeStatus
from apps.customer_success.services import outcome_tracker

pytestmark = pytest.mark.django_db


def test_an_outcome_starts_on_plan(paying_client):
    outcome = outcome_tracker.create(paying_client, title="Reduce inference latency")
    assert outcome.status == OutcomeStatus.ON_PLAN


def test_achieving_stamps_the_time(paying_client):
    outcome = outcome_tracker.create(paying_client, title="Ship the integration")
    outcome_tracker.set_status(outcome, OutcomeStatus.ACHIEVED)
    outcome.refresh_from_db()
    assert outcome.achieved_at is not None


def test_off_plan_is_visible_to_the_nba_rule(paying_client):
    outcome = outcome_tracker.create(paying_client, title="Cut GPU spend")
    outcome_tracker.set_status(outcome, OutcomeStatus.OFF_PLAN, note="Blocked on data access")
    assert outcome_tracker.any_off_plan(paying_client) is True


def test_at_risk_also_counts_as_off_plan_for_the_guardrail(paying_client):
    """
    At risk outranks expansion too. Waiting for full failure before suppressing a sales
    motion is waiting too long.
    """
    outcome = outcome_tracker.create(paying_client, title="Hit the benchmark")
    outcome_tracker.set_status(outcome, OutcomeStatus.AT_RISK)
    assert outcome_tracker.any_off_plan(paying_client) is True


def test_the_model_has_no_field_for_an_internal_sales_target(paying_client):
    """
    STRUCTURAL. §12B: never show an internal sales target, a pipeline stage, or a
    commercial probability in this section. There is nowhere to put one.
    """
    from apps.customer_success.models import Outcome

    names = {f.name for f in Outcome._meta.get_fields()}
    for forbidden in ("pipeline_stage", "probability", "deal_value", "arr", "quota"):
        assert forbidden not in names


def test_the_status_note_is_customer_visible(paying_client):
    """Why a status is what it is must be readable, and therefore plain."""
    from apps.customer_success.serializers import OutcomeSerializer

    assert "statusNote" in OutcomeSerializer.Meta.fields
