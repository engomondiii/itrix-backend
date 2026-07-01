"""
Approval router — the approval queue's write side (Backend v4 §6).

    queue_for_approval(message, decision)  → create/return an ApprovalRequest
    approve(request, actor, ...)           → apply the L4/L5 second-approver rule; on
                                             full approval, flip the held Message to
                                             APPROVED and re-broadcast it (governed)
    edit(request, actor, new_body)         → approve with edited wording
    reject(request, actor, reason)         → mark the held Message BLOCKED

Every action is auditable and idempotent-ish: a resolved request is not re-resolved.
L4/L5 require two DISTINCT approvers — the first approval moves the request to
``awaiting_second``; a different approver completes it.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.governance.models import ApprovalRequest, ApprovalStatus

logger = logging.getLogger("itrix")


class ApprovalError(Exception):
    """Raised on an invalid approval action (already resolved, same approver, etc.)."""


@transaction.atomic
def queue_for_approval(
    *,
    message_id: str,
    conversation_id: str = "",
    lead=None,
    client_id: str = "",
    agent_key: str = "",
    claim_level: int = 3,
    draft_body: str = "",
    cited_chunk_ids: list[str] | None = None,
) -> ApprovalRequest:
    """Create (or return the open) ApprovalRequest for a held message."""
    existing = ApprovalRequest.objects.filter(
        message_id=str(message_id), status__in=[ApprovalStatus.PENDING, ApprovalStatus.AWAITING_SECOND]
    ).first()
    if existing:
        return existing

    req = ApprovalRequest.objects.create(
        message_id=str(message_id),
        conversation_id=str(conversation_id or ""),
        lead=lead,
        client_id=client_id or "",
        agent_key=agent_key or "",
        claim_level=claim_level,
        draft_body=draft_body or "",
        cited_chunk_ids=cited_chunk_ids or [],
        status=ApprovalStatus.PENDING,
    )
    logger.info("Queued approval request %s (L%s, msg=%s)", req.id, claim_level, message_id)
    _notify_console(req)
    return req


def _notify_console(req: ApprovalRequest) -> None:
    """Best-effort approval.new push to the team console group (no-op if realtime off)."""
    try:
        from apps.conversations.services.fan_out import _group_send

        _group_send(
            "console",
            {
                "type": "approval.new",
                "approval_id": str(req.id),
                "lead_id": str(req.lead_id) if req.lead_id else None,
                "claim_level": req.claim_level,
            },
        )
    except Exception:  # noqa: BLE001
        logger.debug("approval.new console push skipped")


@transaction.atomic
def approve(request: ApprovalRequest, *, actor, final_body: str | None = None) -> ApprovalRequest:
    """
    Approve a request. For L4/L5 the first approval moves it to ``awaiting_second``; a
    DIFFERENT approver then completes it. Lower levels complete on the first approval.
    """
    if request.is_resolved:
        raise ApprovalError("This request is already resolved.")

    if final_body is not None:
        request.final_body = final_body

    if request.requires_second_approver:
        if request.status == ApprovalStatus.PENDING:
            # First approval.
            request.first_approver = actor
            request.status = ApprovalStatus.AWAITING_SECOND
            request.save(update_fields=["first_approver", "final_body", "status", "updated_at"])
            logger.info("Approval %s first-approved; awaiting second approver", request.id)
            return request
        # awaiting_second → require a distinct approver.
        if request.first_approver_id and actor and request.first_approver_id == actor.id:
            raise ApprovalError("A second, distinct approver is required for L4/L5.")
        request.second_approver = actor

    _finalize(request, actor=actor, status=ApprovalStatus.APPROVED)
    return request


@transaction.atomic
def edit(request: ApprovalRequest, *, actor, new_body: str) -> ApprovalRequest:
    """Approve with edited wording (records EDITED). Applies the same second-approver rule."""
    if request.is_resolved:
        raise ApprovalError("This request is already resolved.")
    request.final_body = new_body

    if request.requires_second_approver and request.status == ApprovalStatus.PENDING:
        request.first_approver = actor
        request.status = ApprovalStatus.AWAITING_SECOND
        request.save(update_fields=["first_approver", "final_body", "status", "updated_at"])
        return request
    if request.requires_second_approver:
        if request.first_approver_id and actor and request.first_approver_id == actor.id:
            raise ApprovalError("A second, distinct approver is required for L4/L5.")
        request.second_approver = actor

    _finalize(request, actor=actor, status=ApprovalStatus.EDITED)
    return request


@transaction.atomic
def reject(request: ApprovalRequest, *, actor, reason: str = "") -> ApprovalRequest:
    """Reject a request — the held message is marked BLOCKED and never delivered."""
    if request.is_resolved:
        raise ApprovalError("This request is already resolved.")
    request.status = ApprovalStatus.REJECTED
    request.reason = reason
    request.resolved_at = timezone.now()
    request.first_approver = request.first_approver or actor
    request.save(update_fields=["status", "reason", "resolved_at", "first_approver", "updated_at"])

    _apply_to_message(request, deliver=False)
    logger.info("Approval %s rejected: %s", request.id, reason)
    return request


def _finalize(request: ApprovalRequest, *, actor, status: str) -> None:
    request.status = status
    request.resolved_at = timezone.now()
    request.save(
        update_fields=["status", "final_body", "second_approver", "resolved_at", "updated_at"]
    )
    _apply_to_message(request, deliver=True)
    logger.info("Approval %s finalized as %s", request.id, status)


def _apply_to_message(request: ApprovalRequest, *, deliver: bool) -> None:
    """Flip the held conversation Message to APPROVED/BLOCKED and re-broadcast if delivered."""
    if not request.message_id:
        # A standalone agent run (no conversation message) — nothing to flip/broadcast.
        return
    try:
        from apps.conversations.models import GovernanceStatus, Message
        from apps.conversations.services import fan_out

        msg = Message.objects.filter(id=request.message_id).first()
        if msg is None:
            return
        if deliver:
            if request.final_body:
                msg.body = request.final_body
            msg.governance_status = GovernanceStatus.APPROVED
            msg.save(update_fields=["body", "governance_status", "updated_at"])
            fan_out.broadcast_message(msg)
        else:
            msg.governance_status = GovernanceStatus.BLOCKED
            msg.save(update_fields=["governance_status", "updated_at"])
    except Exception:  # noqa: BLE001
        logger.exception("Failed to apply approval %s to its message", request.id)
