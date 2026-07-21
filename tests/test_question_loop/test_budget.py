"""Question budgets and the generator's fallback behaviour (§5.3, §5.4)."""

from __future__ import annotations

import pytest

from apps.agents.services import coverage as coverage_svc
from apps.agents.services import question_generator as qg
from apps.agents.services import question_history, stop_rule

pytestmark = pytest.mark.django_db


def _coverage():
    return coverage_svc.CoverageMap(
        dimensions={d: coverage_svc.UNKNOWN for d in coverage_svc.LISTENING_DIMENSIONS}
    )


def test_the_generator_falls_back_to_the_bank_when_generation_is_off(thread):
    """
    A loop that silently stopped asking because the model was down would terminate
    qualification early and build an artifact from half the information.
    """
    question = qg.generate(thread=thread, coverage=_coverage(), journey_state=2)
    assert question.primary
    assert question.generated is False


def test_the_first_question_targets_a_required_dimension(thread):
    question = qg.generate(thread=thread, coverage=_coverage(), journey_state=2)
    assert question.target_dimension in ("workload", "pressure_area", "platform_environment")


def test_successive_questions_target_different_dimensions(thread):
    """Asking the same dimension again with different words is still asking again."""
    seen = set()
    for _ in range(3):
        question = qg.generate(thread=thread, coverage=_coverage(), journey_state=2)
        qg.emit(thread, question)
        seen.add(question.target_dimension)
    assert len(seen) == 3


def test_emitting_records_the_question(thread):
    question = qg.generate(thread=thread, coverage=_coverage(), journey_state=2)
    qg.emit(thread, question)
    assert question_history.count_for(thread) == 1


def test_a_fallback_question_still_counts_toward_the_budget(thread):
    """A fallback question was still ASKED — not counting it would break the budget."""
    for _ in range(3):
        qg.emit(thread, qg.generate(thread=thread, coverage=_coverage(), journey_state=2))
    decision = stop_rule.evaluate(coverage=_coverage(), journey_state=2,
                                  questions_asked=question_history.count_for(thread))
    assert decision.should_continue is False
    assert decision.reason == stop_rule.STOP_BUDGET


def test_the_payload_carries_no_dimension(thread):
    """``target_dimension`` is internal — the visitor never learns what we are probing."""
    question = qg.generate(thread=thread, coverage=_coverage(), journey_state=2)
    payload = question.to_payload()
    assert set(payload) == {"primary", "chips"}


def test_when_everything_is_covered_no_question_is_produced(thread):
    coverage = _coverage()
    for dimension in coverage.dimensions:
        coverage.dimensions[dimension] = coverage_svc.COVERED
    question = qg.generate(thread=thread, coverage=coverage, journey_state=2)
    assert question.primary == ""


def test_emit_on_an_empty_question_records_nothing(thread):
    qg.emit(thread, qg.GeneratedQuestion(primary="", chips=[]))
    assert question_history.count_for(thread) == 0
