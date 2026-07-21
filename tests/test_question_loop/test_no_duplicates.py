"""
Duplicate suppression (Backend v6.0 §5.4).

The risk register names it alongside non-termination: *the question loop never
terminates, OR ASKS THE SAME THING REPEATEDLY*. From the visitor's side they are the same
failure — being asked what platform you use for a third time does not read as
thoroughness, it reads as not listening.
"""

from __future__ import annotations

import pytest

from apps.agents.services import question_history

pytestmark = pytest.mark.django_db


def test_identical_questions_are_duplicates():
    assert question_history.similarity(
        "What does the workload run on?", "What does the workload run on?"
    ) == 1.0


def test_rephrasings_are_caught():
    """
    'What does the workload run on?' and 'What platform does the workload run on?' are
    the same question wearing different words.
    """
    score = question_history.similarity(
        "What does the workload run on?",
        "What platform does the workload run on?",
    )
    assert score >= question_history.SIMILARITY_THRESHOLD


def test_different_questions_are_not_duplicates():
    score = question_history.similarity(
        "What does the workload run on?",
        "Is this a now problem or a next-year problem?",
    )
    assert score < question_history.SIMILARITY_THRESHOLD


def test_a_recorded_question_is_detected_as_a_duplicate(thread):
    question_history.record(thread, primary="What does the workload run on?",
                            target_dimension="platform_environment")
    assert question_history.is_duplicate(thread, "What does the workload run on?") is True


def test_an_unasked_question_is_not_a_duplicate(thread):
    question_history.record(thread, primary="What does the workload run on?",
                            target_dimension="platform_environment")
    assert question_history.is_duplicate(
        thread, "If this were solved, what would it unlock?"
    ) is False


def test_an_empty_question_is_treated_as_a_duplicate(thread):
    """Refusing to emit nothing is the same decision as refusing to repeat."""
    assert question_history.is_duplicate(thread, "") is True


def test_targeted_dimensions_are_tracked(thread):
    question_history.record(thread, primary="What does it run on?",
                            target_dimension="platform_environment")
    assert "platform_environment" in question_history.dimensions_already_targeted(thread)


def test_the_count_feeds_the_budget(thread):
    for i in range(3):
        question_history.record(thread, primary=f"Question number {i} about things?",
                                target_dimension=f"d{i}")
    assert question_history.count_for(thread) == 3
