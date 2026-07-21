"""
Governed fan-out.

Deliver a persisted message to the conversation's realtime subscribers — but only if it
is deliverable (auto-approved / approved). Held or blocked drafts are announced as an
"under review" state instead of their content, so unapproved wording never reaches a
client (Backend v4 §4.2 "streaming with a safety net").

Fan-out is best-effort and fully optional: when ENABLE_REALTIME is off (or Channels is
not installed), it is a no-op and the persisted message is simply read back via the REST
history endpoint. This keeps the request/response funnel working without a broker.

── EVENT SHAPE (v4.0.3) ──────────────────────────────────────────────────────
Events are dispatched to consumer group handlers (``message_final`` / ``message_delta`` /
``message_under_review`` / ``journey_reveal``) which reshape them into the frontend's
``{ "type": ..., "payload": {...} }`` camelCase contract before sending. So here we carry
a ready-made ``payload`` dict on each event; the consumer just forwards ``event["payload"]``.
"""

from __future__ import annotations

import logging

from django.conf import settings

from apps.conversations.models import Message

logger = logging.getLogger("itrix")


def _channel_layer():
    if not getattr(settings, "ENABLE_REALTIME", False):
        return None
    try:
        from channels.layers import get_channel_layer

        return get_channel_layer()
    except Exception:  # noqa: BLE001 - channels not installed / not configured
        return None


def _group_send(group_name: str, event: dict) -> None:
    layer = _channel_layer()
    if layer is None:
        logger.debug("fan_out no-op (realtime off): %s", event.get("type"))
        return
    try:
        from asgiref.sync import async_to_sync

        async_to_sync(layer.group_send)(group_name, event)
    except Exception:  # noqa: BLE001
        logger.exception("fan_out group_send failed for %s", group_name)


def broadcast_message(message: Message) -> None:
    """Fan a persisted message out to its conversation group (governed)."""
    conv = message.conversation
    conv_id = str(conv.id)
    if message.is_deliverable:
        _group_send(
            conv.group_name,
            {
                # Channels handler name (dots → underscores): message_final
                "type": "message.final",
                "payload": {
                    "conversationId": conv_id,
                    "message": {
                        "id": str(message.id),
                        "conversationId": conv_id,
                        "senderKind": message.sender_kind,
                        "agentKey": message.agent_key or None,
                        "body": message.body,
                        "citations": [
                            {"chunkId": c, "label": None} for c in (message.cited_chunk_ids or []) if c
                        ],
                        "governanceStatus": message.governance_status,
                        "streaming": False,
                        "createdAt": message.created_at.isoformat(),
                    },
                },
            },
        )
    else:
        _group_send(
            conv.group_name,
            {
                "type": "message.under_review",
                "payload": {
                    "conversationId": conv_id,
                    "messageId": str(message.id),
                    "governanceStatus": message.governance_status,
                },
            },
        )


def broadcast_delta(conversation_group: str, *, conversation_id: str, message_id: str, token: str) -> None:
    """Stream one token of an in-flight agent reply (optional; used by consumers)."""
    _group_send(
        conversation_group,
        {
            "type": "message.delta",
            "payload": {
                "conversationId": conversation_id,
                "messageId": message_id,
                "delta": token,
                "senderKind": "agent",
                "agentKey": "concierge",
            },
        },
    )


def broadcast_reveal(group_name: str, reveal: dict) -> None:
    """Push a journey.reveal to a subject's channel group."""
    if not reveal:
        return
    _group_send(
        group_name,
        {
            "type": "journey.reveal",
            "state": reveal.get("state"),
            "surface": reveal.get("surface"),
            "capability_token": reveal.get("capability_token"),
            "value_delivered": reveal.get("value_delivered", True),
            "account_invite_available": reveal.get("account_invite_available", False),
        },
    )


def broadcast_presence(group_name: str, participants: list[dict]) -> None:
    _group_send(group_name, {"type": "presence.update", "payload": {"present": participants}})


def govern_and_broadcast(message) -> str:
    """
    Governance pass for an OUTBOUND message (agent or team→client) before delivery.

    Runs the Governance meta-agent over the message body; if auto-approved it is delivered
    (broadcast). Otherwise the message is flipped to its held governance status, an
    ApprovalRequest is queued (L4/L5 require a second approver), and only the "under
    review" state is announced — never the unapproved content.

    Returns the final governance status string. Best-effort: if governance is unavailable
    the message is held (conservative) rather than delivered.
    """
    from apps.conversations.models import GovernanceStatus

    try:
        from apps.agents.services.governance import govern_text

        decision = govern_text(
            message.body, claim_level=message.claim_level, context=message.conversation.context
        )
    except Exception:  # noqa: BLE001
        logger.exception("govern_and_broadcast: governance unavailable; holding message")
        message.governance_status = GovernanceStatus.PENDING
        message.save(update_fields=["governance_status", "updated_at"])
        broadcast_message(message)
        return GovernanceStatus.PENDING

    if decision["status"] == "auto_approved":
        if decision.get("text") and decision["text"] != message.body:
            message.body = decision["text"]
        message.governance_status = GovernanceStatus.AUTO_APPROVED
        message.save(update_fields=["body", "governance_status", "updated_at"])
        broadcast_message(message)
        return GovernanceStatus.AUTO_APPROVED

    if decision["status"] == "blocked":
        message.governance_status = GovernanceStatus.BLOCKED
    else:
        message.governance_status = GovernanceStatus.PENDING
    message.save(update_fields=["governance_status", "updated_at"])

    if decision["status"] != "blocked":
        try:
            from apps.governance.services.approval_router import queue_for_approval

            conv = message.conversation
            queue_for_approval(
                message_id=str(message.id),
                conversation_id=str(conv.id),
                lead=conv.lead,
                client_id=str(conv.client_id or ""),
                agent_key=message.agent_key,
                claim_level=message.claim_level,
                draft_body=message.body,
                cited_chunk_ids=message.cited_chunk_ids,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to queue approval for message %s", message.id)

    broadcast_message(message)
    return message.governance_status


# ─────────────────────────────────────────────────────────────────────────────
# v6.0 events
# ─────────────────────────────────────────────────────────────────────────────
def broadcast_shell_update(group_name: str, contract: dict) -> None:
    """
    Push ``shell.update`` — the event that REPLACES ``rail.update``.

    Carries the sidebar sections, the conversation header and the composer label so an
    open conversation re-renders its shell WITHOUT a navigation. ``rail.update`` is
    removed; a client still listening for it simply never hears one.
    """
    if not contract:
        return
    _group_send(
        group_name,
        {
            # Channels handler name (dots -> underscores): shell_update
            "type": "shell.update",
            "payload": {
                "journeyState": contract.get("journey_state"),
                "stateKey": contract.get("state_key"),
                "sidebarSections": contract.get("sidebar_sections", []),
                "conversationHeader": _camel_header(contract.get("conversation_header") or {}),
                "composerLabel": contract.get("composer_label"),
                "questionLoopOpen": bool(contract.get("question_loop_open")),
                "attachmentsEnabled": bool(contract.get("attachments_enabled")),
                "identityState": contract.get("identity_state"),
                # disclosure_ceiling is safe to send: it tells the client what tier it
                # may DISPLAY, not what it may fetch. Every fetch is re-authorized
                # server-side regardless.
                "disclosureCeiling": contract.get("disclosure_ceiling"),
            },
        },
    )


def _camel_header(header: dict) -> dict:
    return {
        "title": header.get("title"),
        "stateLabel": header.get("state_label"),
        "humanOwner": header.get("human_owner"),
        "supportSla": header.get("support_sla"),
        "quickHelp": bool(header.get("quick_help")),
    }


def broadcast_thread_updated(thread) -> None:
    """Push ``thread.updated`` — title, state or ownership changed."""
    if thread is None:
        return
    _group_send(
        getattr(thread, "group_name", f"thread.{getattr(thread, 'id', '')}"),
        {
            "type": "thread.updated",
            "payload": {
                "threadId": str(getattr(thread, "id", "")),
                "title": getattr(thread, "title", "") or "",
                "state": getattr(thread, "state_at_creation", "") or "",
                "claimed": getattr(thread, "claimed_at", None) is not None,
            },
        },
    )


def broadcast_halted(group_name: str, payload: dict) -> None:
    """
    Push ``message.halted``.

    The payload carries NO partial text — the client DISCARDS what it has rendered. That
    is the difference between a halt and a correction: a corrected message admits the
    reader saw the original.
    """
    _group_send(group_name, {"type": "message.halted", "payload": payload})


def broadcast_question_suggested(group_name: str, payload: dict) -> None:
    """Push ``question.suggested`` — the primary question plus up to three chips."""
    _group_send(group_name, {"type": "question.suggested", "payload": payload})
