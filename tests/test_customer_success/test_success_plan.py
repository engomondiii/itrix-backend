"""The shared 30/60/90 plan (Playbook §12F)."""

from __future__ import annotations

import pytest

from apps.customer_success.services import success_plan

pytestmark = pytest.mark.django_db


def test_an_active_plan_is_created_once(paying_client):
    first = success_plan.get_or_create_active(paying_client)
    second = success_plan.get_or_create_active(paying_client)
    assert first.id == second.id


def test_dependencies_on_the_customer_are_surfaced_separately(paying_client):
    """
    "We have flagged them early so they do not surprise anyone." A dependency the
    customer does not know about will be missed and then blamed on whoever mentions it
    last.
    """
    plan = success_plan.get_or_create_active(paying_client)
    success_plan.add_milestone(plan, title="Provide benchmark access",
                               needs_customer_action=True)
    success_plan.add_milestone(plan, title="Run the transformation")

    pending = success_plan.pending_customer_actions(paying_client)
    assert pending.count() == 1
    assert pending.first().title == "Provide benchmark access"


def test_a_completed_dependency_stops_being_pending(paying_client):
    plan = success_plan.get_or_create_active(paying_client)
    milestone = success_plan.add_milestone(plan, title="Send the workload",
                                           needs_customer_action=True)
    success_plan.complete_milestone(milestone)
    assert success_plan.pending_customer_actions(paying_client).count() == 0


def test_the_summary_counts_what_awaits_the_customer(paying_client):
    plan = success_plan.get_or_create_active(paying_client)
    success_plan.add_milestone(plan, title="Approve the baseline", needs_customer_action=True)
    summary = success_plan.plan_summary(paying_client)
    assert summary["has_plan"] is True
    assert summary["awaiting_customer"] == 1


def test_no_plan_is_an_honest_empty_state(paying_client):
    summary = success_plan.plan_summary(paying_client)
    assert summary["has_plan"] is False
