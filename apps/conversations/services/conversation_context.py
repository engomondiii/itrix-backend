"""
Conversation memory for the live turn path.

── THE PROBLEM THIS SOLVES ──────────────────────────────────────────────────
The conversational surface generated every reply from the CURRENT turn alone. The
prompt handed to the model was literally "Visitor question: <what they just typed>"
with no prior turns, so from the model's point of view every message was a first
contact — which is exactly why "proceed" produced "Welcome, glad you're curious"
and why answered qualification questions were asked again.

The memory machinery already existed but was never called:
``context_assembly.assemble()`` builds a budgeted, priority-ordered context that
INCLUDES recent turns and rolling summaries of closed states. This module is the
thin bridge that reads a thread's turns and hands them to that assembler, so both
the HTTP and the WebSocket generation paths can give the model its memory.

── WHAT IT RETURNS ──────────────────────────────────────────────────────────
``recent_turns(thread, ...)`` returns a list of "Speaker: text" lines for the
turns of the CURRENT state, oldest first, EXCLUDING the visitor turn that is being
answered right now (that is passed to the assembler separately as the current
turn, and priority 3 already protects it). ``closed_state_summaries(thread)``
returns the deterministic rolling summaries of earlier states.

Nothing here generates text. The summaries are the deterministic ones from
``context_assembly`` — a generated summary replayed into every later turn would be
un-governed model text on the context of every subsequent turn, which is the very
surface the governance fabric exists to close.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("itrix")

# How many recent turns to replay in full. The assembler still applies the real
# character budget on top of this; this is a sane upper bound so a very long thread
# does not build a giant list only to have most of it trimmed.
DEFAULT_RECENT_TURNS = 12


def _speaker(message) -> str:
    kind = getattr(message, "sender_kind", "") or ""
    return "Visitor" if kind in {"visitor", "client"} else "itriX"


def recent_turns(thread, *, exclude_message_id: str | None = None, limit: int = DEFAULT_RECENT_TURNS) -> list[str]:
    """
    Recent turns of THIS conversation as "Speaker: text" lines, oldest first.

    Excludes halted/discarded turns (they were never delivered) and, when given,
    the message id of the turn currently being answered — that turn is the
    assembler's ``current_turn`` and must not appear twice.
    """
    if thread is None:
        return []
    try:
        from apps.conversations.models import Message

        qs = (
            Message.objects.filter(thread=thread)
            .exclude(streaming_status="halted")
            .order_by("seq", "created_at")
        )
        rows = list(qs)
    except Exception:  # noqa: BLE001 - memory is best-effort; never break a turn
        logger.debug("recent_turns query failed for thread %s", getattr(thread, "id", "?"))
        return []

    lines: list[str] = []
    for message in rows:
        if exclude_message_id and str(getattr(message, "id", "")) == str(exclude_message_id):
            continue
        body = " ".join((getattr(message, "body", "") or "").split())
        if not body:
            continue
        lines.append(f"{_speaker(message)}: {body}")

    # Keep only the most recent `limit`, but preserve chronological order.
    if limit and len(lines) > limit:
        lines = lines[-limit:]
    return lines


def closed_state_summaries(thread) -> list[str]:
    """
    Deterministic rolling summaries of the thread's CLOSED states.

    Phase 1 keeps this conservative: it returns at most one rolling summary built by
    ``context_assembly.summarize_thread_state``. It exists so the seam is in place —
    when multi-state summarisation lands, this is the single place it grows, and the
    generation paths need no change.
    """
    if thread is None:
        return []
    try:
        from apps.conversations.services import context_assembly

        state_key = _current_state_key(thread)
        summary = context_assembly.summarize_thread_state(thread, state_key)
        return [summary] if summary else []
    except Exception:  # noqa: BLE001
        logger.debug("closed_state_summaries failed for thread %s", getattr(thread, "id", "?"))
        return []


def _current_state_key(thread) -> str:
    try:
        from apps.conversations.services.thread_state import current_state_key

        return current_state_key(thread)
    except Exception:  # noqa: BLE001
        return "ARRIVED"


def build_turn_extra(thread, body: str, *, exclude_message_id: str | None = None) -> dict:
    """
    The ``AgentContext.extra`` payload for one turn, WITH conversation memory.

    Both the HTTP and the WebSocket generation paths build their ``AgentContext``
    with this, so the model sees the same memory whichever transport delivered the
    turn. It always includes the current message; it includes prior turns, closed-
    state summaries and the real journey state whenever the thread has them.

    Keys:
        message                 the current visitor turn (unchanged contract)
        thread_id               the thread id (unchanged contract)
        recent_turns            prior turns as "Speaker: text" lines (may be empty)
        closed_state_summaries  deterministic summaries of earlier states (may be empty)
        journey_state           the thread's current state key (e.g. "IN_REVIEW")
        client_page_reveal      set when this turn revealed the personalised page
        contact_ask             set when this turn's reply must ask for an email
    """
    extra: dict = {"message": body, "thread_id": str(getattr(thread, "id", "") or "")}
    if thread is None:
        return extra
    try:
        extra["recent_turns"] = recent_turns(thread, exclude_message_id=exclude_message_id)
        extra["closed_state_summaries"] = closed_state_summaries(thread)
        extra["journey_state"] = _current_state_key(thread)
        # If a client page was revealed for this turn (stashed on the thread during
        # ingest), pass it through so the agent presents the page in its own words
        # instead of promising a human follow-up.
        reveal = getattr(thread, "_client_page_reveal", None)
        if reveal:
            extra["client_page_reveal"] = reveal
        # And if the reveal is waiting on an email address nobody has asked for,
        # pass that decision through too, so the agent asks for it in its own words
        # instead of ending on a promise of human follow-up.
        ask = getattr(thread, "_contact_ask", None)
        if ask:
            extra["contact_ask"] = ask
    except Exception:  # noqa: BLE001 - memory is additive; never break generation
        logger.debug("build_turn_extra memory assembly failed for thread %s", getattr(thread, "id", "?"))
    return extra
