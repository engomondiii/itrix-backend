"""
THE COVERAGE READ — row-level (Backend v7.1 Phase 2).

Which of the ten listening dimensions a thread has covered, and what covered each one.

── WHY THE EVIDENCE MATTERS MORE THAN THE SCORE ────────────────────────────

A coverage map is easy to build and easy to misread. "7 of 10 covered" tells an operator
almost nothing useful; what they need to know is WHICH dimension is missing and WHY the
system thinks the others are done — because the interesting failure is a dimension marked
covered on the strength of a passing mention.

So every row carries ``evidenceMessageId``. "Why is this covered?" has an answer, and an
operator can go and read the turn that satisfied it. A coverage map without evidence is a
number an operator learns to ignore, which is the same failure mode as a health class
without reasons.

INTERNAL-ONLY in its entirety (§10.5). ``coverage_map`` is on the list of fields that must
not appear on the anonymous or client plane at any state — a visitor being shown which
boxes the system is still trying to tick would turn a conversation into an interrogation
they can see the shape of.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("itrix")


def for_thread(thread_id: str) -> dict | None:
    """
    The coverage map for one thread, in the canonical dimension order.

    Dimensions with NO snapshot are returned as ``unknown`` rather than omitted. That is
    the whole point of the read: the absent ones are what an operator is looking for, and
    omitting them would make a thread that has covered nothing look identical to one that
    has covered everything.
    """
    from apps.conversations.models import Thread
    from apps.journey.constants import LISTENING_DIMENSIONS
    from apps.journey.models_artifacts import CoverageSnapshot

    thread = Thread.objects.filter(id=thread_id).first()
    if thread is None:
        return None

    snapshots = {
        snap.dimension: snap
        for snap in CoverageSnapshot.objects.filter(thread_id=thread.id)
    }

    dimensions = []
    for name in LISTENING_DIMENSIONS:
        snap = snapshots.get(name)
        dimensions.append(
            {
                "dimension": name,
                "status": getattr(snap, "status", "unknown") or "unknown",
                # "Why is this covered?" must have an answer.
                "evidenceMessageId": getattr(snap, "evidence_message_id", "") or None,
                "updatedAt": snap.updated_at.isoformat() if snap else None,
            }
        )

    covered = sum(1 for d in dimensions if d["status"] == "covered")
    partial = sum(1 for d in dimensions if d["status"] == "partial")

    return {
        "threadId": str(thread.id),
        "dimensions": dimensions,
        "covered": covered,
        "partial": partial,
        "unknown": len(dimensions) - covered - partial,
        "total": len(dimensions),
        # Named rather than left for a chart to infer, so nobody renders a percentage that
        # treats `partial` as half a dimension. It is not half — it is a dimension the
        # system has a hint about and has not established.
        "statuses": ["unknown", "partial", "covered"],
        # A dimension marked covered on a passing mention is the interesting failure, so the
        # read says plainly what covered means here.
        "interpretation": (
            "A dimension is covered when a turn established it, not when it was mentioned. "
            "Open the evidence message before trusting a covered row."
        ),
    }
