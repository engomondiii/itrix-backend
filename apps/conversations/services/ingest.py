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
    # ── MESSAGING FAN-OUT (Celery integration, 2026-08-10) ───────────────────
    # A client message used to land silently: it persisted, the client saw it in
    # their own thread, and the team found out only if somebody happened to open
    # the cockpit. Client turns only ever originate from the portal (HTTP view or
    # the portal WebSocket consumer — both funnel through here), so this single
    # guarded hook notifies the team for both transports.
    if sender_kind == SenderKind.CLIENT and msg.sender_client is not None:
        _notify_team_of_client_message(msg)
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

    # Advance the qualification loop for this turn. This handles BOTH the first-turn
    # transition (1 -> 2) and — via the coverage tracker + stop rule — closing the loop
    # (2 -> 3) once the band is satisfied. It works for anonymous (lead-less) threads as
    # well as identified ones, which the old ``on_first_turn``-only hook did not: it
    # returned early for anonymous visitors, so their state never moved and the intro
    # re-fired on every turn. Deterministic; best-effort; never blocks the persisted turn.
    try:
        from apps.conversations.services import qualification

        qualification.advance_on_turn(thread, body)
    except Exception:  # noqa: BLE001 - state advancement is best-effort
        logger.debug("qualification advance skipped for thread %s", getattr(thread, "id", "?"))


def _notify_team_of_client_message(message) -> None:
    """
    In-app team notification for a new CLIENT (portal) message.

    Best-effort, like every other post-turn hook: the client's message is already on the
    record and must never be lost to a notification hiccup. When ``ENABLE_CELERY`` is on
    the notification is enqueued ON COMMIT — the task re-reads nothing from this row, but
    a worker racing an uncommitted transaction is exactly the class of bug on_commit
    exists to close, and it also means a rolled-back message never produces a phantom
    alert. With Celery off, the row is written inline, same as the lead fan-out.

    The body deliberately carries NO message text: the notification tray is a pointer,
    and the message itself is read in the cockpit under its own authorization.
    """
    try:
        from django.conf import settings
        from django.db import transaction

        client = message.sender_client
        who = (
            getattr(client, "organization", "")
            or getattr(client, "full_name", "")
            or getattr(client, "email", "")
            or "A client"
        )
        lead = getattr(client, "lead", None)
        kind = "system"  # Notification.Kind.SYSTEM — no schema change (notify_journey_event precedent)
        title = f"New client message: {who}"
        body = "A client wrote to the team in their workspace Messaging."
        href = f"/leads/{lead.id}" if lead is not None else ""

        if getattr(settings, "ENABLE_CELERY", False):
            from tasks.notification_tasks import create_notification_task

            lead_id = str(lead.id) if lead is not None else ""
            transaction.on_commit(
                lambda: create_notification_task.delay(kind, title, body, href, lead_id=lead_id)
            )
        else:
            from apps.notifications.services.notification_creator import create_notification

            create_notification(kind=kind, title=title, body=body, href=href, lead=lead)
    except Exception:  # noqa: BLE001 - the persisted turn outranks its fan-out
        logger.exception(
            "client-message notification failed for message %s", getattr(message, "id", "?")
        )


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

    ── THE LINK IS FILTERED TO THE MESSAGE'S OWN THREAD (2026-08-13) ────────────
    This used to link whatever id it was handed. That was safe only because the two
    callers happened to filter first (``agents.views._own_thread_attachments``) or work
    from an already-scoped list. Now that the PUBLIC ``threads/`` routes call it, an
    unfiltered link is an IDOR: naming a stranger's attachment id in ``attachment_ids``
    would attach their document to your own turn, and the turn serializer renders what is
    linked. So membership is re-checked HERE, against the message's thread, and the
    boundary no longer depends on each call site remembering to do it.

    A single query resolves the whole list, so a long ``attachment_ids`` costs one round
    trip rather than one per id.
    """
    if not attachment_ids:
        return 0
    linked = 0
    try:
        from apps.attachments.models import Attachment
        from apps.conversations.models import MessageAttachment

        thread_id = getattr(message, "thread_id", None)
        if thread_id is None:
            logger.warning(
                "attachment association skipped: message %s has no thread", message.id
            )
            return 0

        wanted = [str(a) for a in attachment_ids if a]
        if not wanted:
            return 0

        allowed = {
            str(pk)
            for pk in Attachment.objects.filter(
                id__in=wanted, thread_id=thread_id, deleted_at__isnull=True
            ).values_list("id", flat=True)
        }
        refused = [a for a in wanted if a not in allowed]
        if refused:
            logger.warning(
                "attachment association refused %s id(s) not on thread %s for message %s",
                len(refused), thread_id, message.id,
            )

        # Order follows the CALLER's list, not the query, so the transcript shows the
        # files in the order the visitor attached them.
        for order, attachment_id in enumerate(a for a in wanted if a in allowed):
            MessageAttachment.objects.get_or_create(
                message=message,
                attachment_id=attachment_id,
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
    thread=None,
) -> Message:
    """
    Persist a team→client turn (governed like any outbound message).

    ── IT MUST LAND ON THE THREAD (fix, 2026-08-12) ─────────────────────────────
    This function used to create the Message with NO ``thread`` and NO ``seq``,
    while its sibling ``ingest_agent_message`` resolved both. Every transcript
    read — the visitor's, the portal's, the cockpit's — queries BY THREAD, so a
    staff reply written here was persisted correctly and then rendered nowhere.
    The reply existed; nobody could see it.

    ``seq`` matters for the same reason and one more: the realtime sequence is what
    lets a client detect a GAP and re-fetch. A message left at seq 0 sits before
    the visitor's first turn in any ordered read, so even a client that found it
    would show it in the wrong place.

    ``thread`` stays a parameter (defaulting to the conversation's own) because the
    console can be replying inside a specific thread of a conversation, and the
    caller knows which. ``_thread_for`` returns None for the shipped review and
    client-page conversations that predate the spine — those still persist, exactly
    as before, rather than failing on a missing thread.
    """
    thread = thread or _thread_for(conversation)
    msg = Message.objects.create(
        conversation=conversation,
        thread=thread,
        seq=_next_seq(thread),
        sender_kind=SenderKind.TEAM,
        sender_user=user,
        body=body or "",
        governance_status=governance_status,
        meta=meta or {},
    )
    history.touch(conversation)
    if thread is not None:
        try:
            from apps.conversations.services import threads as thread_svc

            thread_svc.touch(thread)
        except Exception:  # noqa: BLE001 - a touch failure must not lose the reply
            pass
    return msg
