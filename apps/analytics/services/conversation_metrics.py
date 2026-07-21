"""
Conversation analytics (Backend v6.0 §Phase 3).

    thread depth · turns-to-artifact · loop productivity · stop_reason distribution ·
    abandonment

── LOOP PRODUCTIVITY IS THE ONE THAT EARNS ITS PLACE ────────────────────────
§5.4: the cockpit must be able to audit WHETHER THE LOOP WAS PRODUCTIVE. Three questions
that all targeted the same dimension is a broken loop, and without ``target_dimension``
it looks identical to three good questions. This module is where that becomes visible.

All of it is INTERNAL-ONLY: ``coverage_map``, ``question_budget_remaining`` and
``stop_reason`` are on the §10.5 list.
"""

from __future__ import annotations

import logging

from django.db.models import Avg, Count
from django.utils import timezone

logger = logging.getLogger("itrix")

# A thread with no activity for this long and no artifact is treated as abandoned.
ABANDONMENT_HOURS = 24


def thread_depth() -> dict:
    """How many turns a conversation typically reaches."""
    from apps.conversations.models import Message, Thread

    counts = (
        Message.objects.filter(thread__isnull=False)
        .values("thread_id")
        .annotate(n=Count("id"))
    )
    depths = sorted(row["n"] for row in counts)
    total_threads = Thread.objects.count()
    if not depths:
        return {"threads": total_threads, "median": 0, "mean": 0, "p90": 0, "max": 0}

    def percentile(values, fraction):
        if not values:
            return 0
        index = min(len(values) - 1, int(len(values) * fraction))
        return values[index]

    return {
        "threads": total_threads,
        "median": percentile(depths, 0.5),
        "mean": round(sum(depths) / len(depths), 2),
        "p90": percentile(depths, 0.9),
        "max": depths[-1],
    }


def turns_to_artifact() -> dict:
    """
    How many turns it takes to deliver the first artifact.

    The headline number for whether the question loop is efficient. A rising value means
    we are asking more to learn the same amount.
    """
    from apps.conversations.models import Message
    from apps.journey.models_artifacts import Artifact

    samples: list[int] = []
    first_artifacts = (
        Artifact.objects.order_by("thread_id", "created_at")
        .values("thread_id", "created_at")
    )
    seen: set[str] = set()
    for row in first_artifacts:
        key = str(row["thread_id"])
        if key in seen:
            continue
        seen.add(key)
        turns = Message.objects.filter(
            thread_id=row["thread_id"],
            sender_kind__in=["visitor", "client"],
            created_at__lte=row["created_at"],
        ).count()
        if turns:
            samples.append(turns)

    if not samples:
        return {"samples": 0, "mean": None, "median": None}
    samples.sort()
    return {
        "samples": len(samples),
        "mean": round(sum(samples) / len(samples), 2),
        "median": samples[len(samples) // 2],
    }


def loop_productivity() -> dict:
    """
    Whether questions are covering NEW ground.

    ``distinctRatio`` is the number that matters: distinct dimensions targeted divided by
    questions asked. 1.0 means every question opened new ground. A falling ratio means the
    loop is circling — which reads to a visitor as not listening.
    """
    from apps.journey.models_artifacts import QuestionSuggestion

    total = QuestionSuggestion.objects.count()
    if not total:
        return {"questions": 0, "distinctDimensions": 0, "distinctRatio": None,
                "threadsWithRepeats": 0}

    distinct = (
        QuestionSuggestion.objects.exclude(target_dimension="")
        .values("target_dimension")
        .distinct()
        .count()
    )

    repeats = 0
    per_thread = (
        QuestionSuggestion.objects.exclude(target_dimension="")
        .values("thread_id", "target_dimension")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
    )
    repeats = len({row["thread_id"] for row in per_thread})

    ratio_base = (
        QuestionSuggestion.objects.exclude(target_dimension="")
        .values("thread_id", "target_dimension")
        .distinct()
        .count()
    )
    asked = QuestionSuggestion.objects.exclude(target_dimension="").count()

    return {
        "questions": total,
        "distinctDimensions": distinct,
        "distinctRatio": round(ratio_base / asked, 3) if asked else None,
        "threadsWithRepeats": repeats,
    }


def stop_reason_distribution() -> dict:
    """
    Why the loop stopped.

    A healthy distribution is dominated by ``dimensions_covered``. A spike in
    ``question_budget_exhausted`` means we are running out of budget before we
    understand; a spike in ``visitor_declined`` means the questions are unwelcome.
    """
    from apps.review.models import ReviewSession

    try:
        rows = (
            ReviewSession.objects.exclude(stop_reason="")
            .values("stop_reason")
            .annotate(n=Count("id"))
        )
        return {row["stop_reason"]: row["n"] for row in rows}
    except Exception:  # noqa: BLE001 - field lands with the Phase-3 migration
        return {}


def abandonment() -> dict:
    """
    Threads that went quiet without producing anything.

    Counted as a RATE alongside the raw number, because a rising count during growth is
    not the same as a rising rate.
    """
    from apps.conversations.models import Message, Thread
    from apps.journey.models_artifacts import Artifact

    cutoff = timezone.now() - timezone.timedelta(hours=ABANDONMENT_HOURS)
    stale = Thread.objects.filter(last_activity_at__lt=cutoff)
    with_artifact = set(
        str(t) for t in Artifact.objects.values_list("thread_id", flat=True).distinct()
    )

    abandoned = 0
    engaged_then_abandoned = 0
    for thread in stale.only("id"):
        if str(thread.id) in with_artifact:
            continue
        abandoned += 1
        if Message.objects.filter(thread=thread, sender_kind__in=["visitor", "client"]).count() >= 2:
            engaged_then_abandoned += 1

    total = Thread.objects.count()
    return {
        "abandoned": abandoned,
        # The more worrying number: they engaged, then left anyway.
        "engagedThenAbandoned": engaged_then_abandoned,
        "totalThreads": total,
        "rate": round(abandoned / total, 3) if total else None,
        "windowHours": ABANDONMENT_HOURS,
    }


def summary() -> dict:
    return {
        "threadDepth": thread_depth(),
        "turnsToArtifact": turns_to_artifact(),
        "loopProductivity": loop_productivity(),
        "stopReasons": stop_reason_distribution(),
        "abandonment": abandonment(),
    }
