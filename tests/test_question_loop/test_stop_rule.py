"""
The deterministic stop rule (Backend v6.0 §5.3).

The answer to "what stops this thing asking questions forever?". The risk register names
it: *the question loop never terminates, or asks the same thing repeatedly*.

Order matters — the EARLIEST condition wins. A visitor asking for a human outranks an
unmet coverage requirement, because continuing to qualify someone who asked for a person
is the rudest possible outcome.
"""

from __future__ import annotations

import pytest

from apps.agents.services import coverage as coverage_svc
from apps.agents.services import stop_rule

pytestmark = pytest.mark.django_db


def _empty_coverage():
    return coverage_svc.CoverageMap(
        dimensions={d: coverage_svc.UNKNOWN for d in coverage_svc.LISTENING_DIMENSIONS}
    )


def test_the_loop_continues_when_nothing_is_covered():
    decision = stop_rule.evaluate(coverage=_empty_coverage(), journey_state=2,
                                  questions_asked=0)
    assert decision.should_continue is True


def test_covered_dimensions_stop_the_loop():
    coverage = _empty_coverage()
    for dimension in ("workload", "pressure_area", "platform_environment"):
        coverage.dimensions[dimension] = coverage_svc.COVERED
    decision = stop_rule.evaluate(coverage=coverage, journey_state=2, questions_asked=1)
    assert decision.should_continue is False
    assert decision.reason == stop_rule.STOP_COVERED


def test_the_budget_stops_the_loop():
    decision = stop_rule.evaluate(coverage=_empty_coverage(), journey_state=2,
                                  questions_asked=3)
    assert decision.should_continue is False
    assert decision.reason == stop_rule.STOP_BUDGET


def test_stage_two_gets_one_more_question():
    assert stop_rule.question_budget(2) == 3
    assert stop_rule.question_budget(6) == 4


@pytest.mark.parametrize("text", [
    "no more questions please",
    "stop asking, that's all",
    "I'd rather not say",
])
def test_a_declining_visitor_stops_the_loop(text):
    decision = stop_rule.evaluate(coverage=_empty_coverage(), journey_state=2,
                                  questions_asked=0, last_visitor_text=text)
    assert decision.should_continue is False
    assert decision.reason == stop_rule.STOP_VISITOR_DECLINED


@pytest.mark.parametrize("text", [
    "just tell me what you recommend",
    "get to the point",
    "show me the brief",
])
def test_asking_for_the_outcome_stops_the_loop(text):
    decision = stop_rule.evaluate(coverage=_empty_coverage(), journey_state=2,
                                  questions_asked=0, last_visitor_text=text)
    assert decision.should_continue is False
    assert decision.reason == stop_rule.STOP_ASKED_FOR_OUTCOME


@pytest.mark.parametrize("text", [
    "can I speak to a real person",
    "I want to talk to someone",
    "have a human call me",
])
def test_asking_for_a_human_stops_the_loop(text):
    decision = stop_rule.evaluate(coverage=_empty_coverage(), journey_state=2,
                                  questions_asked=0, last_visitor_text=text)
    assert decision.should_continue is False
    assert decision.reason == stop_rule.STOP_ASKED_FOR_HUMAN


def test_a_human_request_outranks_missing_coverage():
    """
    ORDER MATTERS. Continuing to qualify someone who asked for a person is the rudest
    possible outcome, so it must beat every other condition.
    """
    decision = stop_rule.evaluate(coverage=_empty_coverage(), journey_state=2,
                                  questions_asked=0,
                                  last_visitor_text="please have someone call me")
    assert decision.reason == stop_rule.STOP_ASKED_FOR_HUMAN


def test_a_sensitivity_signal_hands_off_to_governance():
    decision = stop_rule.evaluate(coverage=_empty_coverage(), journey_state=2,
                                  questions_asked=0,
                                  last_visitor_text="this work is ITAR controlled")
    assert decision.reason == stop_rule.STOP_GOVERNANCE_HANDOFF


def test_sensitivity_outranks_everything():
    decision = stop_rule.evaluate(coverage=_empty_coverage(), journey_state=2,
                                  questions_asked=0,
                                  last_visitor_text="just tell me — it is classified work")
    assert decision.reason == stop_rule.STOP_GOVERNANCE_HANDOFF


def test_the_loop_always_terminates_within_the_budget():
    """The property that matters: it cannot run forever."""
    coverage = _empty_coverage()
    for asked in range(0, 10):
        decision = stop_rule.evaluate(coverage=coverage, journey_state=2,
                                      questions_asked=asked)
        if not decision.should_continue:
            assert asked <= stop_rule.question_budget(2)
            return
    pytest.fail("the loop did not terminate within the budget")


def test_the_rule_makes_no_model_call():
    """Asserted on imports, not prose — see the note in test_coverage.py."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(stop_rule))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    for module in imported:
        lowered = module.lower()
        for forbidden in ("claude", "openai", "anthropic", "ai_engine"):
            assert forbidden not in lowered, (
                f"stop_rule imports {module!r} — Layer 1 must stay LLM-free"
            )


def test_the_stop_reason_is_recorded():
    decision = stop_rule.evaluate(coverage=_empty_coverage(), journey_state=2,
                                  questions_asked=3)
    assert decision.reason
    assert decision.budget_remaining == 0
