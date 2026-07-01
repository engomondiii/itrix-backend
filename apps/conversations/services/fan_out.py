"""
Governed fan-out.

Deliver a persisted message to the conversation's realtime subscribers — but only if it
is deliverable (auto-approved / approved). Held or blocked drafts are announced as an
"under review" state instead of their content, so unapproved wording never reaches a
client (Backend v4 §4.2 "streaming with a safety net").

Fan-out is best-effort and fully optional: when ENABLE_REALTIME is off (or Channels is
not installed), it is a no-op and the persisted message is simply read back via the REST
history endpoint. This keeps the request/response funnel working without a broker.
"""

from __future__ import annotations

import logging

from django.conf import settings

from apps.conversations.models import GovernanceStatus, Message

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
    if message.is_deliverable:
        _group_send(
            conv.group_name,
            {
                "type": "message.final",
                "message_id": str(message.id),
                "conversation_id": str(conv.id),
                "sender_kind": message.sender_kind,
                "agent_key": message.agent_key,
                "body": message.body,
                "cited_chunk_ids": message.cited_chunk_ids,
                "governance_status": message.governance_status,
                "created_at": message.created_at.isoformat(),
            },
        )
    else:
        # Held for approval — announce the "under review" state, never the content.
        _group_send(
            conv.group_name,
            {
                "type": "message.under_review",
                "message_id": str(message.id),
                "conversation_id": str(conv.id),
                "governance_status": message.governance_status,
            },
        )


def broadcast_delta(conversation_group: str, *, message_id: str, token: str) -> None:
    """Stream one token of an in-flight agent reply (optional; used by consumers)."""
    _group_send(
        conversation_group,
        {"type": "message.delta", "message_id": message_id, "token": token},
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
        },
    )


def broadcast_presence(group_name: str, participants: list[dict]) -> None:
    _group_send(group_name, {"type": "presence.update", "participants": participants})


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

    # Not auto-approved → hold + queue for human approval.
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

    broadcast_message(message)  # announces the under-review state (never the content)
    return message.governance_status
