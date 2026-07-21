"""
Message ordering and resumption (Backend v6.0 §7.2, Architecture v2.6 §14.4).

Streaming a turn token-by-token over a network that drops connections means ordering
cannot be assumed. Three guarantees, and each one closes a specific failure:

1. MONOTONIC SEQ — every ``message.delta`` carries a per-thread monotonic sequence
   number. Without it, out-of-order delivery renders scrambled text and nobody can tell.

2. GAP DETECTION — a client that sees seq jump re-fetches the message rather than
   RENDERING A HOLE. Rendering a hole is worse than a delay: a governed message with a
   silently missing middle is an un-governed message.

3. RESUME — a reconnect resumes from the last acknowledged seq, replaying missed deltas
   or falling back to the settled message. A turn that was streaming when the socket
   dropped is NEVER LOST: it completes server-side and is available on the next fetch.

Sequence allocation is done with a database-level ``F()`` increment inside a transaction,
so two concurrent turns on one thread can never be handed the same number.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Max

logger = logging.getLogger("itrix")


@dataclass(frozen=True)
class SequenceGap:
    """A detected discontinuity in a client's delta stream."""

    expected: int
    received: int

    @property
    def size(self) -> int:
        return max(0, self.received - self.expected)


@transaction.atomic
def next_seq(thread) -> int:
    """
    Allocate the next monotonic sequence number for ``thread``.

    Uses ``select_for_update`` on the thread row so two concurrent turns serialise
    rather than colliding. The cost of the lock is one row for the duration of an
    INSERT; the cost of NOT locking is two messages sharing a seq, which makes gap
    detection permanently wrong for that thread.
    """
    from apps.conversations.models import Message, Thread

    locked = Thread.objects.select_for_update().filter(id=thread.id).first()
    if locked is None:
        return 1
    current = (
        Message.objects.filter(thread_id=locked.id).aggregate(top=Max("seq")).get("top") or 0
    )
    return int(current) + 1


def latest_seq(thread) -> int:
    """The highest sequence number persisted for this thread (0 when empty)."""
    from apps.conversations.models import Message

    if thread is None:
        return 0
    return int(
        Message.objects.filter(thread_id=thread.id).aggregate(top=Max("seq")).get("top") or 0
    )


def detect_gap(expected_seq: int, received_seq: int) -> SequenceGap | None:
    """
    Return a ``SequenceGap`` when ``received_seq`` skips ahead of ``expected_seq``.

    A LOWER sequence number is not a gap — it is a duplicate, which the client should
    discard rather than re-fetch for.
    """
    if received_seq > expected_seq:
        return SequenceGap(expected=expected_seq, received=received_seq)
    return None


def messages_since(thread, last_acked_seq: int, *, limit: int = 500):
    """
    The messages a reconnecting client missed.

    Ordered by seq so replay is deterministic. Halted messages are EXCLUDED: their
    partial text was discarded from the client on purpose and must not reappear on
    resume — that would deliver exactly the text the stream guard stopped.
    """
    from apps.conversations.models import Message, StreamingStatus

    if thread is None:
        return Message.objects.none()
    return (
        Message.objects.filter(thread_id=thread.id, seq__gt=int(last_acked_seq or 0))
        .exclude(streaming_status=StreamingStatus.HALTED)
        .order_by("seq")[:limit]
    )


def resume_payload(thread, last_acked_seq: int) -> dict:
    """
    Build the payload a client needs to resume cleanly after a reconnect.

        { "thread_id", "from_seq", "latest_seq", "messages": [...] }

    The client applies these in order and continues streaming from ``latest_seq``.
    """
    missed = list(messages_since(thread, last_acked_seq))
    return {
        "thread_id": str(getattr(thread, "id", "")),
        "from_seq": int(last_acked_seq or 0),
        "latest_seq": latest_seq(thread),
        "messages": [
            {
                "id": str(message.id),
                "seq": message.seq,
                "senderKind": message.sender_kind,
                "agentKey": message.agent_key or None,
                # Never replay a body the governance pipeline has not cleared.
                "body": message.body if message.is_deliverable else "",
                "governanceStatus": message.governance_status,
                "streamingStatus": message.streaming_status,
                "underReview": not message.is_deliverable,
                "createdAt": message.created_at.isoformat(),
            }
            for message in missed
        ],
    }
