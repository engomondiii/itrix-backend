"""Conversation analytics (Backend v6.0 §Phase 3)."""

from __future__ import annotations

import pytest

from apps.analytics.services import conversation_metrics
from apps.conversations.services import ingest, threads as thread_svc

pytestmark = pytest.mark.django_db


def _thread_with(turns: int, session="s-metrics"):
    thread = thread_svc.create_thread(visitor_session=session)
    for i in range(turns):
        ingest.ingest_inbound(thread.conversation, sender_kind="visitor",
                              body=f"turn {i}", thread=thread)
    return thread


def test_thread_depth_reports_a_distribution():
    _thread_with(3)
    _thread_with(1, session="s-2")
    depth = conversation_metrics.thread_depth()
    assert depth["threads"] >= 2
    assert depth["max"] >= 3


def test_an_empty_dataset_does_not_divide_by_zero():
    depth = conversation_metrics.thread_depth()
    assert depth["mean"] is not None


def test_loop_productivity_reports_the_distinct_ratio():
    """
    The number that matters: 1.0 means every question opened new ground. A falling ratio
    means the loop is circling, which reads to a visitor as not listening.
    """
    from apps.agents.services import question_history

    thread = _thread_with(1)
    question_history.record(thread, primary="What does it run on?",
                            target_dimension="platform_environment")
    question_history.record(thread, primary="What is the workload?",
                            target_dimension="workload")
    productivity = conversation_metrics.loop_productivity()
    assert productivity["questions"] == 2
    assert productivity["distinctRatio"] == 1.0
    assert productivity["threadsWithRepeats"] == 0


def test_a_repeated_dimension_is_visible():
    """
    Three questions on the same dimension is a broken loop, and without
    ``target_dimension`` it looks identical to three good ones.
    """
    from apps.agents.services import question_history

    thread = _thread_with(1)
    question_history.record(thread, primary="What does it run on?",
                            target_dimension="platform_environment")
    question_history.record(thread, primary="Which platform exactly?",
                            target_dimension="platform_environment")
    assert conversation_metrics.loop_productivity()["threadsWithRepeats"] == 1


def test_turns_to_artifact_is_measured():
    from apps.journey.constants import ARTIFACT_REFLECTION
    from apps.journey.services import artifacts

    thread = _thread_with(2)
    artifacts.generate(thread, ARTIFACT_REFLECTION, force=True)
    result = conversation_metrics.turns_to_artifact()
    assert result["samples"] >= 1
    assert result["mean"] is not None


def test_no_artifacts_reports_none_rather_than_zero():
    _thread_with(2)
    assert conversation_metrics.turns_to_artifact()["mean"] is None


def test_abandonment_separates_engaged_from_bounced():
    """
    "They engaged, then left anyway" is the more worrying number and is reported
    separately from a single-turn bounce.
    """
    from django.utils import timezone

    from apps.conversations.models import Thread

    thread = _thread_with(3)
    Thread.objects.filter(id=thread.id).update(
        last_activity_at=timezone.now() - timezone.timedelta(days=3)
    )
    result = conversation_metrics.abandonment()
    assert result["abandoned"] >= 1
    assert result["engagedThenAbandoned"] >= 1


def test_abandonment_reports_a_rate_alongside_the_count():
    """A rising count during growth is not the same as a rising rate."""
    _thread_with(1)
    assert "rate" in conversation_metrics.abandonment()


def test_the_summary_assembles_every_metric():
    summary = conversation_metrics.summary()
    for key in ("threadDepth", "turnsToArtifact", "loopProductivity",
                "stopReasons", "abandonment"):
        assert key in summary
