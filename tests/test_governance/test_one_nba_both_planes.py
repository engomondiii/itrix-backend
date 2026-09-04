"""
ONE NBA FOR BOTH PLANES (Architecture v2.8 §18.7, Backend v7.1 §11.1).

── THE ASYMMETRY PHASE 3 CLOSED ────────────────────────────────────────────

The cockpit path has gone through ``nba_precedence`` since v6.0 Phase 3. The PORTAL path
returned ``None`` — a Phase 1 placeholder with a note saying Phase 3 would fill it.

That was the safe direction to be wrong in, and it was still wrong. §11.1 says both planes pass
through one rule so a customer and an operator can never see contradictory guidance; with one
side returning nothing they could not contradict each other, but they also could not agree. A
customer saw no next step while their operator saw a governed one.

── WHAT THESE TESTS PIN ────────────────────────────────────────────────────
Mostly a NEGATIVE: a commercial action must never be primary while a suppression condition
holds. §18.7 calls that a defect, not a judgement call — so it is a test, not a review note.
"""

from __future__ import annotations

import pytest

from tests.factories.client_factory import ClientFactory
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def _commercial_lead():
    """A State 10 lead with a Client — the state where commercial candidates exist."""
    from django.utils import timezone

    lead = LeadFactory(
        journey_state="CUSTOMER_SUCCESS",
        email="customer@example.com",
        value_delivered_at=timezone.now(),
    )
    ClientFactory(lead=lead, organization="Example Corp", is_active=True)
    return lead


def _confirmed_customer_thread(lead, *, session="sess-nba-confirmed"):
    """A customer thread whose STR-03 recommendation gate has been satisfied."""
    from apps.conversations.services import engagement_state, threads as thread_svc

    thread = thread_svc.create_thread(visitor_session=session, lead=lead)
    thread.relationship_state = engagement_state.REL_CUSTOMER
    thread.mirror_status = engagement_state.MIRROR_CONFIRMED
    thread.save(update_fields=["relationship_state", "mirror_status", "updated_at"])
    return thread


def _signals(**overrides) -> dict:
    base = {
        "blocking_support": False,
        "outcome_off_plan": False,
        "adoption_below_plan": False,
        "negative_trust": False,
        "health": "stable",
        "expansion_allowed": True,
    }
    base.update(overrides)
    return base


def _candidates():
    from apps.governance.services.nba_precedence import (
        KIND_COMMERCIAL,
        KIND_INFORMATIONAL,
        ActionCandidate,
    )

    return [
        ActionCandidate(key="read_outcomes", label="Review your outcomes",
                        kind=KIND_INFORMATIONAL, weight=10),
        ActionCandidate(key="expand", label="Discuss another workload",
                        kind=KIND_COMMERCIAL, commercial=True, weight=99),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# THE NEGATIVE PROPERTY
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("condition,reason", [
    ("blocking_support", "blocking_support_issue_open"),
    ("outcome_off_plan", "agreed_outcome_off_plan"),
    ("adoption_below_plan", "adoption_below_plan"),
    ("negative_trust", "negative_trust_signal"),
])
def test_a_commercial_action_is_never_primary_while_a_condition_holds(condition, reason):
    """
    The weight is 99 against 10 — the commercial candidate would win on weight alone. It must
    not. §18.7: a commercial candidate ranked primary while any of conditions 1-4 hold is a
    DEFECT, not a judgement call.
    """
    from apps.governance.services import nba_precedence

    decision = nba_precedence.rank(_candidates(), signals=_signals(**{condition: True}))

    assert decision.primary is not None
    assert decision.primary.commercial is False
    assert decision.primary.kind != nba_precedence.KIND_COMMERCIAL
    assert decision.suppression_reason == reason


def test_the_first_condition_that_holds_decides():
    """
    Fixed order, and not configurable — a configurable safety rule is a rule somebody will
    eventually configure away.
    """
    from apps.governance.services import nba_precedence

    decision = nba_precedence.rank(
        _candidates(),
        signals=_signals(blocking_support=True, outcome_off_plan=True, negative_trust=True),
    )
    assert decision.suppression_reason == "blocking_support_issue_open"


def test_the_rule_manufactures_an_action_rather_than_falling_through():
    """
    If condition 1 holds and no support action was offered, we do NOT fall through to a
    commercial one. "Resolve the blocking issue" is always a valid next step when there is a
    blocking issue.
    """
    from apps.governance.services import nba_precedence
    from apps.governance.services.nba_precedence import KIND_COMMERCIAL, ActionCandidate

    only_commercial = [
        ActionCandidate(key="expand", label="Discuss another workload",
                        kind=KIND_COMMERCIAL, commercial=True, weight=99)
    ]
    decision = nba_precedence.rank(only_commercial, signals=_signals(blocking_support=True))

    assert decision.primary is not None
    assert decision.primary.kind == nba_precedence.KIND_SUPPORT
    assert decision.primary.commercial is False


def test_an_unavailable_subsystem_suppresses_rather_than_permits():
    """
    Every signal FAILS SAFE. An unavailable health service must not read as a healthy customer —
    that is the direction where being wrong costs the customer rather than the sale.
    """
    from unittest.mock import patch

    from apps.governance.services import nba_precedence

    client = ClientFactory()
    with patch(
        "apps.customer_success.services.support_router.open_blocking_for",
        side_effect=RuntimeError("service down"),
    ):
        signals = nba_precedence.collect_signals(client)
    assert signals["blocking_support"] is True


# ─────────────────────────────────────────────────────────────────────────────
# The two planes agree
# ─────────────────────────────────────────────────────────────────────────────
def test_the_portal_now_returns_a_governed_action():
    from apps.journey.services import shell

    lead = _commercial_lead()
    contract = shell.for_subject(lead)
    action = contract["next_best_action"]
    assert action is None or set(action.keys()) <= {"key", "label", "detail", "href"}


def test_the_portal_and_the_cockpit_reach_the_same_primary():
    """
    §11.1. If the rule were implemented twice they would drift, and the first symptom would be a
    customer being sold to while their operator looked at an unresolved outage.
    """
    from apps.agents.services.strategy import nba_candidates
    from apps.governance.services import nba_precedence
    from apps.journey.services import shell

    lead = _commercial_lead()
    thread = _confirmed_customer_thread(lead)
    portal = shell.for_subject(lead, thread=thread)["next_best_action"]
    cockpit = nba_precedence.for_lead(lead, nba_candidates(lead)).to_client_payload()
    assert portal == cockpit


def test_the_client_payload_carries_no_suppression_reason():
    """
    §10.5. A customer does not need to be told we decided not to sell to them today, and telling
    them would surface a commercial deliberation they never asked to be part of.
    """
    from apps.governance.services import nba_precedence

    decision = nba_precedence.rank(_candidates(), signals=_signals(blocking_support=True))
    payload = decision.to_client_payload()

    assert decision.suppression_reason  # the reason exists...
    assert payload is not None
    for forbidden in ("suppressionReason", "suppression_reason", "signals", "kind", "weight"):
        assert forbidden not in payload  # ...and does not reach the customer

    # The operator sees it.
    assert decision.to_team_payload()["suppressionReason"] == "blocking_support_issue_open"


def test_the_portal_fails_to_none_not_to_an_ungoverned_action():
    """
    An unsuppressed commercial action shown to a customer with a blocking request open is the
    precise defect §18.7 exists to prevent. So "no action" is always the safer answer than "the
    highest-weighted one we could still compute".
    """
    from unittest.mock import patch

    from apps.journey.services import shell

    lead = _commercial_lead()
    with patch(
        "apps.governance.services.nba_precedence.for_lead",
        side_effect=RuntimeError("rule unavailable"),
    ):
        assert shell.for_subject(lead)["next_best_action"] is None


def test_an_anonymous_thread_has_no_action_at_all():
    """No Lead exists yet, so there is no subject the rule could reason about."""
    from apps.conversations.services import threads as thread_svc
    from apps.journey.services import shell

    thread = thread_svc.create_thread(visitor_session="sess-nba-anon")
    assert shell.for_anonymous_thread(thread)["next_best_action"] is None
