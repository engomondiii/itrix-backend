"""
Governance halts as ROWS (Backend v7.1 §Phase 1).

``analytics/streaming/`` answers "is the halt rate rising?". This answers "what exactly
did the model try to say, and on which thread?" — which is the question an operator has
when the answer to the first one is yes.

── §6.4's INTERPRETATION RULE APPLIES TO THIS ENDPOINT TOO ─────────────────
A halt is not a success story about the guard working. It is a signal that a model tried
to say something it should never have been in a position to say, and the interesting
question is what changed upstream in retrieval or the prompt. The rows are ordered newest
first because drift is diagnosed from the recent ones.

── matchedText IS ROLE-FILTERED HERE, SERVER-SIDE ──────────────────────────
ADMIN and ASSESSMENT only. For everyone else the key is ABSENT — not empty. An empty
string reads as "nothing was matched", which is false and would make a VIEWER think the
halt was spurious.

The filter is server-side because a frontend that hid the field would still have received
it: the bytes would be in the JSON, in the browser cache, and in anything that logged the
response.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("itrix")

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


def rows(
    *,
    limit: int = DEFAULT_LIMIT,
    may_see_matched_text: bool = False,
    thread_id: str | None = None,
    category: str | None = None,
) -> list[dict]:
    """
    Recent halts, newest first.

    ``may_see_matched_text`` is a PARAMETER rather than something read from a request here:
    a service that reached for the request could be called from somewhere with none and
    would then have to guess. The default is the restrictive one.
    """
    from apps.governance.models import StreamGuardHit

    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))

    qs = StreamGuardHit.objects.all()
    if thread_id:
        qs = qs.filter(thread_id=thread_id)
    if category:
        qs = qs.filter(category=category)

    out: list[dict] = []
    for hit in qs.order_by("-created_at")[:limit]:
        row = {
            "id": str(hit.id),
            "kind": hit.kind,
            "category": hit.category,
            # The pattern IDENTIFIER is safe for every team role: it names which rule fired
            # without reproducing the wording that fired it.
            "pattern": hit.pattern,
            "agentKey": hit.agent_key,
            "plane": hit.plane,
            "journeyState": hit.journey_state,
            "threadId": hit.thread_id,
            "at": hit.created_at.isoformat(),
        }
        if may_see_matched_text:
            row["matchedText"] = hit.matched_text
            # The label travels WITH the data so a UI cannot render the text without it.
            row["matchedTextNotice"] = "Never sent to the visitor."
        out.append(row)
    return out
