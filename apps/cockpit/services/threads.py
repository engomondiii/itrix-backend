"""
The thread board and thread detail — ROW-LEVEL (Backend v7.1 §Phase 1).

    rows()    the board: one row per conversation, newest activity first
    detail()  one conversation, with its internal overlay

── ANONYMOUS THREADS ARE REQUIRED, NOT OPTIONAL ────────────────────────────
Surface 2 v7.0 §06 makes this explicit, and it is worth restating because the
convenient implementation gets it wrong. A board that showed only threads with a Lead
attached would hide exactly the conversations that matter most for oversight: the
first-visit ones, where a visitor is describing a problem and nobody has decided
anything yet. Those are the ones where a governance halt or a bad question does the most
damage, and they are the ones with no Lead.

So the board includes anonymous threads and LABELS them as such.

── AND IT NAMES NOTHING IT HAS NOT BEEN TOLD ───────────────────────────────
No inferred organisation, ever — on this plane or any other. ``company`` is populated
from the Client record when one exists and is empty otherwise. A board that guessed
would be putting a guess in front of an operator who would then repeat it to the
visitor.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("itrix")

# A board is for scanning. Beyond a couple of hundred rows an operator filters rather
# than scrolls, so the PAGE ceiling is a real limit rather than a placeholder.
#
# ── THE CAP WAS NOT A PAGE (fix, 2026-08-12) ────────────────────────────────
# `MAX_LIMIT` used to be the end of the data: `[:limit]` with no offset meant the
# 501st-oldest thread could not be reached by any request. A cap on page SIZE is a
# scanning decision; a cap with no offset is data loss with extra steps. `rows()` now
# takes an offset and reports the total, so every row is reachable and the board can
# say how much is behind it.
DEFAULT_LIMIT = 200
MAX_LIMIT = 500


def _company_for(thread) -> str:
    """
    The organisation, from the Client record only.

    NEVER inferred from a domain, an email, or anything the visitor typed. An inferred
    company shown to an operator becomes an inferred company said out loud to the visitor,
    which is the failure §19 exists to prevent.
    """
    client = getattr(thread, "client", None)
    if client is not None:
        return getattr(client, "organization", "") or ""
    lead = getattr(thread, "lead", None)
    if lead is not None:
        client_id = getattr(lead, "client_id", None)
        if client_id:
            try:
                from apps.clients.models import Client

                found = Client.objects.filter(id=client_id).only("organization").first()
                if found is not None:
                    return found.organization or ""
            except Exception:  # noqa: BLE001
                return ""
    return ""


def page(*, limit: int = DEFAULT_LIMIT, offset: int = 0) -> dict:
    """
    One row per conversation. Newest activity first — the board is a work queue.

    ── THERE IS NO ``is_active`` ON Thread, AND THERE SHOULD NOT BE ─────────
    An earlier draft of this function filtered on ``is_active`` and ordered by
    ``last_message_at``. Neither field exists: the real ones are ``last_activity_at``, and
    Thread has no soft-delete flag at all because a visitor deleting a conversation DELETES
    it — that is the promise made in the Privacy Policy, and a hidden-but-retained row
    would quietly break it.

    So there is no ``includeInactive`` parameter either. A board cannot offer to show
    something the model does not keep.

    Returns ``{results, total, limit, offset, hasMore}``. The ordering carries ``id`` as
    a final tiebreak: two threads touched in the same instant would otherwise be ordered
    arbitrarily, and an unstable sort under paging shows one row twice and skips another.
    """
    from django.db.models import Count, Max, Q

    from apps.conversations.models import SenderKind, Thread

    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    offset = max(0, int(offset or 0))

    # Counted on its own query rather than off the annotated one: the annotations exist
    # to fill the row, and COUNT(*) over three joins to answer "how many threads" is a
    # cost paid on every board load for a number that does not need them.
    total = Thread.objects.count()

    qs = Thread.objects.select_related("lead", "client").annotate(
        turn_count=Count("messages", distinct=True),
        visitor_turns=Count(
            "messages",
            filter=Q(messages__sender_kind=SenderKind.VISITOR),
            distinct=True,
        ),
        newest_message_at=Max("messages__created_at"),
    ).order_by("-last_activity_at", "-created_at", "id")[offset:offset + limit]

    out: list[dict] = []
    for thread in qs:
        lead = getattr(thread, "lead", None)
        out.append(
            {
                "threadId": str(thread.id),
                "title": thread.title or "",
                # THE LABEL, not a filter. Anonymous threads are the ones oversight needs
                # most, and hiding them would defeat the board.
                "anonymous": lead is None and getattr(thread, "client_id", None) is None,
                "leadId": str(lead.id) if lead is not None else None,
                "company": _company_for(thread),
                "journeyState": getattr(lead, "journey_state", "") or "ARRIVED",
                "turnCount": thread.turn_count or 0,
                "visitorTurns": thread.visitor_turns or 0,
                # `shell_mode`'s own threshold, restated as data rather than duplicated as
                # logic: a thread with a visitor turn is one the visitor is working in.
                "working": (thread.visitor_turns or 0) > 0,
                # The model's own column, falling back to the newest message. The two can
                # differ when a thread was touched without a message being written.
                "lastActivityAt": (
                    thread.last_activity_at.isoformat()
                    if thread.last_activity_at
                    else (thread.newest_message_at.isoformat() if thread.newest_message_at else None)
                ),
                "createdAt": thread.created_at.isoformat(),
                # Thread has no soft-delete flag — see the note on this function.
                "ownerKind": getattr(thread, "owner_kind", "") or "",
            }
        )
    return {
        "results": out,
        "total": total,
        "limit": limit,
        "offset": offset,
        "hasMore": offset + len(out) < total,
    }


def rows(*, limit: int = DEFAULT_LIMIT, offset: int = 0) -> list[dict]:
    """
    The board rows alone.

    Kept as the shape every existing caller and test already expects. `page()` is the
    one that also reports the total; this is a thin read of it, so there is no second
    query implementation to drift.
    """
    return page(limit=limit, offset=offset)["results"]


def detail(thread_id: str, *, may_see_matched_text: bool = False) -> dict | None:
    """
    One conversation, with the internal overlay an operator needs.

    ``may_see_matched_text`` is passed in by the view after checking the requester's role.
    It is a PARAMETER rather than something read here on purpose: a service that reached
    for the request would be a service that could be called from somewhere with no
    request, and would then have to guess. The default is the restrictive one.
    """
    from apps.conversations.models import Message, Thread

    thread = (
        Thread.objects.select_related("lead", "client").filter(id=thread_id).first()
    )
    if thread is None:
        return None

    lead = getattr(thread, "lead", None)
    messages = (
        Message.objects.filter(thread_id=thread.id)
        .order_by("seq", "created_at")
        .only(
            "id", "seq", "sender_kind", "agent_key", "body",
            "governance_status", "claim_level", "streaming_status",
            "cited_chunk_ids", "created_at",
        )
    )

    turns = [
        {
            "id": str(m.id),
            "seq": m.seq,
            "senderKind": m.sender_kind,
            "agentKey": m.agent_key or None,
            "body": m.body,
            # The internal overlay: what governance did to this turn, and what it cited.
            # None of this reaches the visitor's plane.
            "governanceStatus": m.governance_status,
            "claimLevel": m.claim_level,
            "streamingStatus": m.streaming_status,
            "citedChunkIds": m.cited_chunk_ids or [],
            "at": m.created_at.isoformat(),
        }
        for m in messages
    ]

    return {
        "threadId": str(thread.id),
        "title": thread.title or "",
        "anonymous": lead is None and getattr(thread, "client_id", None) is None,
        "leadId": str(lead.id) if lead is not None else None,
        "company": _company_for(thread),
        "journeyState": getattr(lead, "journey_state", "") or "ARRIVED",
        # Thread has no soft-delete flag: a visitor deleting a conversation DELETES it,
        # which is the promise made in the Privacy Policy. `ownerKind` is the field that
        # actually says something about the thread's provenance.
        "ownerKind": getattr(thread, "owner_kind", "") or "",
        "createdAt": thread.created_at.isoformat(),
        "lastActivityAt": (
            thread.last_activity_at.isoformat() if thread.last_activity_at else None
        ),
        "turns": turns,
        "guardHits": _guard_hits_for(str(thread.id), may_see_matched_text),
        # Phase 2 adds the coverage read and the attachment rows. Declaring the keys as
        # empty now means the dashboard can render the panels without a second contract
        # change — and an empty list is honest, where an absent key would make the
        # frontend guess whether it failed or there is nothing.
        "coverage": None,
        "attachments": [],
    }


def _guard_hits_for(thread_id: str, may_see_matched_text: bool) -> list[dict]:
    """
    Governance halts on this thread.

    ``matchedText`` is included ONLY for ADMIN and ASSESSMENT. For everyone else the key
    is absent rather than empty — an empty string reads as "nothing was matched", which is
    false and would make a VIEWER think the halt was spurious.
    """
    try:
        from apps.governance.models import StreamGuardHit
    except Exception:  # noqa: BLE001
        return []

    out: list[dict] = []
    for hit in StreamGuardHit.objects.filter(thread_id=thread_id).order_by("-created_at")[:50]:
        row = {
            "id": str(hit.id),
            "kind": hit.kind,
            "category": hit.category,
            "pattern": hit.pattern,
            "agentKey": hit.agent_key,
            "plane": hit.plane,
            "at": hit.created_at.isoformat(),
        }
        if may_see_matched_text:
            row["matchedText"] = hit.matched_text
            # The label travels WITH the data, so a UI cannot render the text without it.
            row["matchedTextNotice"] = "Never sent to the visitor."
        out.append(row)
    return out
