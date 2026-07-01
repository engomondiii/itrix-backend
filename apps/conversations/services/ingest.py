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
) -> Message:
    """Persist a visitor/client/team inbound turn (always deliverable)."""
    msg = Message.objects.create(
        conversation=conversation,
        sender_kind=sender_kind,
        sender_client=client if sender_kind == SenderKind.CLIENT else None,
        sender_user=user if sender_kind == SenderKind.TEAM else None,
        body=body or "",
        governance_status=GovernanceStatus.AUTO_APPROVED,
        meta=meta or {},
    )
    history.touch(conversation)
    return msg


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
) -> Message:
    """Persist an agent-produced turn with its governance decision."""
    msg = Message.objects.create(
        conversation=conversation,
        sender_kind=SenderKind.AGENT,
        agent_key=agent_key,
        body=body or "",
        governance_status=governance_status,
        claim_level=claim_level,
        cited_chunk_ids=cited_chunk_ids or [],
        agent_run_id=agent_run_id,
        meta=meta or {},
    )
    history.touch(conversation)
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
