"""
Message ingest.

Persist a single conversation turn. Inbound turns (visitor/client) are always stored
verbatim and are trivially "delivered" (the subject said them). Outbound turns
(agent/team) carry a governance status: an agent turn's status comes from the agent
runtime's governance decision; a team turn defaults to auto-approved unless the caller
marks it for review.

Ingest is transport-agnostic — it just writes rows + touches the thread. Fan-out over
the WebSocket is a separate concern (services/fan_out.py), so the funnel still works with
ENABLE_REALTIME off (messages persist; the client polls history).
"""

from __future__ import annotations

import logging

from apps.conversations.models import (
    Conversation,
    GovernanceStatus,
    Message,
    SenderKind,
    StreamingStatus,
    validate_message_length,
)
from apps.conversations.services import history

logger = logging.getLogger("itrix")


def ingest_inbound(
    conversation: Conversation,
    *,
    sender_kind: str,
    body: str,
    client=None,
    user=None,
    meta: dict | None = None,
    thread=None,
) -> Message:
    """
    Persist a visitor/client/team inbound turn (always deliverable).

    v6.0: routes the turn into a THREAD and allocates its monotonic seq. Raises
    ``MessageTooLong`` above the server safety cap — there is no user-facing limit, and
    the cap returns a specific, recoverable message rather than silently truncating the
    visitor's problem.
    """
    text = validate_message_length(body)
    thread = thread or _thread_for(conversation)
    seq = _next_seq(thread)

    msg = Message.objects.create(
        conversation=conversation,
        thread=thread,
        seq=seq,
        streaming_status=StreamingStatus.SETTLED,
        sender_kind=sender_kind,
        sender_client=client if sender_kind == SenderKind.CLIENT else None,
        sender_user=user if sender_kind == SenderKind.TEAM else None,
        body=text,
        governance_status=GovernanceStatus.AUTO_APPROVED,
        meta=meta or {},
    )
    history.touch(conversation)
    _after_inbound_turn(thread, msg, text)
    return msg


# ─────────────────────────────────────────────────────────────────────────────
# v6.0 thread routing
# ─────────────────────────────────────────────────────────────────────────────
def _thread_for(conversation: Conversation):
    """
    The Thread this conversation belongs to, if any.

    Nullable by design: the shipped review/client-page conversations predate threads,
    and a turn on one of those must still persist rather than failing on a missing spine.
    """
    return getattr(conversation, "thread", None)


def _next_seq(thread) -> int:
    if thread is None:
        return 0
    try:
        from apps.realtime.services.sequence import next_seq

        return next_seq(thread)
    except Exception:  # noqa: BLE001
        logger.exception("seq allocation failed; falling back to 0")
        return 0


def _after_inbound_turn(thread, message, body: str) -> None:
    """
    Post-turn hooks: title the thread, advance the journey, emit ``thread.updated``.

    Every hook is best-effort. A turn that persisted must never be lost because a
    downstream hook failed — the visitor said it, so it is on the record regardless.
    """
    if thread is None:
        return

    try:
        from apps.conversations.services import threads as thread_svc

        was_untitled = not thread.title or thread.title == thread_svc.DEFAULT_TITLE
        thread_svc.set_title_if_unset(thread, body)
        thread_svc.touch(thread)
        if was_untitled:
            from apps.conversations.services.fan_out import broadcast_thread_updated

            broadcast_thread_updated(thread)
    except Exception:  # noqa: BLE001
        logger.exception("thread post-turn bookkeeping failed")

    # ── v6.0 Phase 2: support-intent routing ─────────────────────────────────
    # A SUPPORT QUESTION IS NEVER ANSWERED WITH A COMMERCIAL ANSWER. Routing happens
    # here, before any agent sees the turn, so the decision is deterministic rather than
    # something the model gets to weigh up.
    _route_support_intent(thread, body)

    # A turn posted on an empty thread starts the review (1 -> 2). Idempotent: a second
    # turn is a satisfied no-op, not an error.
    lead = getattr(thread, "lead", None)
    if lead is None:
        return
    try:
        from apps.journey.services.advance import on_first_turn

        on_first_turn(lead, thread=thread)
    except Exception:  # noqa: BLE001 - an invalid transition here is expected mid-journey
        logger.debug("first-turn advance skipped for lead %s", getattr(lead, "id", "?"))


def _route_support_intent(thread, body: str) -> None:
    """
    Detect a support request on a State 10 thread and route it to a human.

    Deterministic detection (Layer 1 stays LLM-free): if a model decided what counted as
    a support request, a model would be deciding when the commercial-suppression rule
    applies.
    """
    from django.conf import settings

    if not getattr(settings, "ENABLE_CUSTOMER_SUCCESS", False):
        return
    client = getattr(thread, "client", None)
    if client is None:
        return
    try:
        from apps.customer_success.services import support_router

        if not support_router.detect_support_intent(body):
            return
        if not getattr(client, "first_payment_recorded_at", None):
            return
        support_router.route(client, body, thread=thread)
    except Exception:  # noqa: BLE001
        logger.exception("support routing failed for thread %s", getattr(thread, "id", "?"))


def associate_attachments(message, attachment_ids) -> int:
    """
    Link staged attachments to the turn they were sent with.

    Returns how many were linked. A missing attachment is skipped rather than raising —
    the visitor's words are already on the record and must not be lost to a bad id.
    """
    if not attachment_ids:
        return 0
    linked = 0
    try:
        from apps.conversations.models import MessageAttachment

        for order, attachment_id in enumerate(attachment_ids):
            if not attachment_id:
                continue
            MessageAttachment.objects.get_or_create(
                message=message,
                attachment_id=str(attachment_id),
                defaults={"order": order},
            )
            linked += 1
    except Exception:  # noqa: BLE001
        logger.exception("attachment association failed for message %s", message.id)
    return linked


def ingest_agent_message(
    conversation: Conversation,
    *,
    agent_key: str,
    body: str,
    governance_status: str = GovernanceStatus.AUTO_APPROVED,
    claim_level: int = 0,
    cited_chunk_ids: list[str] | None = None,
    agent_run_id: str = "",
    meta: dict | None = None,
    thread=None,
    streaming_status: str = StreamingStatus.SETTLED,
    context_note: str = "",
) -> Message:
    """
    Persist an agent-produced turn with its governance decision.

    ``streaming_status`` records where this message sits in the three-part model, and
    ``context_note`` records anything that could not be considered (§12.5) — the turn
    says so plainly rather than presenting a partial answer as complete.
    """
    thread = thread or _thread_for(conversation)
    msg = Message.objects.create(
        conversation=conversation,
        thread=thread,
        seq=_next_seq(thread),
        streaming_status=streaming_status,
        sender_kind=SenderKind.AGENT,
        agent_key=agent_key,
        body=body or "",
        governance_status=governance_status,
        claim_level=claim_level,
        cited_chunk_ids=cited_chunk_ids or [],
        agent_run_id=agent_run_id,
        context_note=context_note,
        meta=meta or {},
    )
    history.touch(conversation)
    if thread is not None:
        try:
            from apps.conversations.services import threads as thread_svc

            thread_svc.touch(thread)
        except Exception:  # noqa: BLE001
            pass
    return msg


def ingest_team_message(
    conversation: Conversation,
    *,
    user,
    body: str,
    governance_status: str = GovernanceStatus.AUTO_APPROVED,
    meta: dict | None = None,
) -> Message:
    """Persist a team→client turn (governed like any outbound message)."""
    msg = Message.objects.create(
        conversation=conversation,
        sender_kind=SenderKind.TEAM,
        sender_user=user,
        body=body or "",
        governance_status=governance_status,
        meta=meta or {},
    )
    history.touch(conversation)
    return msg
