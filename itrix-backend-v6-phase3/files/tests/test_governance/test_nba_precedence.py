"""
The customer-first precedence rule (Backend v6.0 §Phase 3, Architecture §18.7).

    1. blocking support issue open   -> support action primary
    2. agreed outcome off plan       -> outcome action primary
    3. adoption below plan           -> enablement action primary
    4. negative trust signal         -> human outreach primary
    5. otherwise, and only if expansion_allowed -> commercial eligible

    A COMMERCIAL CANDIDATE RANKED PRIMARY WHILE ANY OF 1-4 HOLD IS A DEFECT,
    NOT A JUDGEMENT CALL.
"""

from __future__ import annotations

import pytest

from apps.governance.services import nba_precedence as nba

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _enable(settings):
    settings.ENABLE_CUSTOMER_FIRST_NBA = True


def _candidates():
    return [
        nba.ActionCandidate(key="expand", label="Expand", kind=nba.KIND_COMMERCIAL,
                            commercial=True, weight=100),
        nba.ActionCandidate(key="support", label="Resolve the issue", kind=nba.KIND_SUPPORT,
                            weight=10),
        nba.ActionCandidate(key="outcome", label="Review the outcome", kind=nba.KIND_OUTCOME,
                            weight=10),
        nba.ActionCandidate(key="enable", label="Enablement", kind=nba.KIND_ENABLEMENT,
                            weight=10),
        nba.ActionCandidate(key="outreach", label="Reach out", kind=nba.KIND_HUMAN_OUTREACH,
                            weight=10),
    ]


def _signals(**overrides):
    base = {
        "blocking_support": False, "outcome_off_plan": False,
        "adoption_below_plan": False, "negative_trust": False,
        "health": "stable", "expansion_allowed": True,
    }
    base.update(overrides)
    return base


def test_condition_1_blocking_support_promotes_support():
    decision = nba.rank(_candidates(), signals=_signals(blocking_support=True))
    assert decision.primary.kind == nba.KIND_SUPPORT
    assert decision.suppression_reason == nba.SUPPRESSED_BLOCKING_SUPPORT


def test_condition_2_off_plan_promotes_outcome():
    decision = nba.rank(_candidates(), signals=_signals(outcome_off_plan=True))
    assert decision.primary.kind == nba.KIND_OUTCOME
    assert decision.suppression_reason == nba.SUPPRESSED_OUTCOME_OFF_PLAN


def test_condition_3_adoption_promotes_enablement():
    decision = nba.rank(_candidates(), signals=_signals(adoption_below_plan=True))
    assert decision.primary.kind == nba.KIND_ENABLEMENT
    assert decision.suppression_reason == nba.SUPPRESSED_ADOPTION_BELOW_PLAN


def test_condition_4_negative_trust_promotes_human_outreach():
    decision = nba.rank(_candidates(), signals=_signals(negative_trust=True))
    assert decision.primary.kind == nba.KIND_HUMAN_OUTREACH
    assert decision.suppression_reason == nba.SUPPRESSED_NEGATIVE_TRUST


@pytest.mark.parametrize("condition", [
    "blocking_support", "outcome_off_plan", "adoption_below_plan", "negative_trust",
])
def test_commercial_is_never_primary_while_a_condition_holds(condition):
    """THE DEFECT CHECK. Highest weight by far, and still suppressed."""
    decision = nba.rank(_candidates(), signals=_signals(**{condition: True}))
    assert decision.primary.commercial is False
    assert decision.primary.kind != nba.KIND_COMMERCIAL


def test_precedence_order_is_fixed():
    """
    With ALL FOUR holding, support wins. Order is not configurable — a configurable
    safety rule is one somebody eventually configures away.
    """
    decision = nba.rank(_candidates(), signals=_signals(
        blocking_support=True, outcome_off_plan=True,
        adoption_below_plan=True, negative_trust=True,
    ))
    assert decision.primary.kind == nba.KIND_SUPPORT


def test_condition_5_allows_commercial_when_everything_is_clear():
    decision = nba.rank(_candidates(), signals=_signals())
    assert decision.primary.commercial is True
    assert decision.suppression_reason == ""


def test_commercial_is_suppressed_when_expansion_is_not_allowed():
    decision = nba.rank(_candidates(), signals=_signals(expansion_allowed=False))
    assert decision.primary.commercial is False
    assert decision.suppression_reason == nba.SUPPRESSED_EXPANSION_NOT_ALLOWED


def test_unknown_health_suppresses_with_its_own_reason():
    """An unmeasured customer is a distinct case from an ineligible one."""
    decision = nba.rank(_candidates(), signals=_signals(health="", expansion_allowed=False))
    assert decision.suppression_reason == nba.SUPPRESSED_HEALTH_UNKNOWN


def test_the_rule_fails_safe_when_no_action_of_the_kind_was_offered():
    """
    If condition 1 holds and NO support action was supplied, we do not fall through to
    the commercial one — we manufacture the support action.
    """
    only_commercial = [nba.ActionCandidate(key="expand", label="Expand",
                                           kind=nba.KIND_COMMERCIAL, commercial=True,
                                           weight=100)]
    decision = nba.rank(only_commercial, signals=_signals(blocking_support=True))
    assert decision.primary.kind == nba.KIND_SUPPORT
    assert decision.primary.commercial is False


def test_a_suppression_reason_is_always_explained():
    """An operator who cannot explain a suppression will work around it."""
    for reason in (
        nba.SUPPRESSED_BLOCKING_SUPPORT, nba.SUPPRESSED_OUTCOME_OFF_PLAN,
        nba.SUPPRESSED_ADOPTION_BELOW_PLAN, nba.SUPPRESSED_NEGATIVE_TRUST,
        nba.SUPPRESSED_EXPANSION_NOT_ALLOWED, nba.SUPPRESSED_HEALTH_UNKNOWN,
    ):
        assert nba.SUPPRESSION_COPY.get(reason)


def test_the_customer_payload_never_carries_the_suppression_reason():
    """
    A customer does not need to be told we decided not to sell to them today — and
    telling them would surface a commercial deliberation they never asked to join.
    """
    decision = nba.rank(_candidates(), signals=_signals(blocking_support=True))
    payload = decision.to_client_payload()
    assert "suppressionReason" not in (payload or {})
    assert "suppression" not in str(payload).lower()


def test_the_team_payload_does_carry_it():
    decision = nba.rank(_candidates(), signals=_signals(blocking_support=True))
    team = decision.to_team_payload()
    assert team["suppressionReason"] == nba.SUPPRESSED_BLOCKING_SUPPORT
    assert team["suppressionCopy"]


def test_signals_fail_safe_when_a_subsystem_is_unavailable():
    """An unavailable health service must not read as a healthy customer."""

    class Broken:
        @property
        def customer_health(self):
            raise RuntimeError("down")

    signals = nba.collect_signals(Broken())
    assert signals["expansion_allowed"] is False


def test_the_flag_makes_the_rule_reversible(settings):
    settings.ENABLE_CUSTOMER_FIRST_NBA = False
    decision = nba.next_best_action(None, _candidates())
    # Pre-Phase-3 behaviour: highest weight wins.
    assert decision.primary.key == "expand"
    assert decision.suppression_reason == ""
