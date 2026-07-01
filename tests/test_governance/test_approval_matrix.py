"""Approval matrix: queue, approve/edit/reject, message delivery on approval."""

from __future__ import annotations

import pytest

from apps.conversations.models import GovernanceStatus, Message
from apps.conversations.services import ingest
from apps.conversations.services.history import get_or_create_portal_conversation
from apps.governance.models import ApprovalRequest, ApprovalStatus
from apps.governance.services import approval_router
from tests.factories.client_factory import ClientFactory
from tests.factories.user_factory import AdminUserFactory

pytestmark = pytest.mark.django_db


def _held_message():
    client = ClientFactory()
    conv = get_or_create_portal_conversation(client)
    msg = ingest.ingest_agent_message(
        conv, agent_key="objection", body="draft body", governance_status=GovernanceStatus.PENDING, claim_level=3
    )
    return conv, msg


def test_queue_and_approve_delivers_message():
    conv, msg = _held_message()
    req = approval_router.queue_for_approval(
        message_id=str(msg.id), conversation_id=str(conv.id), claim_level=3, draft_body=msg.body
    )
    approval_router.approve(req, actor=AdminUserFactory())
    msg.refresh_from_db()
    assert msg.governance_status == GovernanceStatus.APPROVED


def test_reject_blocks_message():
    conv, msg = _held_message()
    req = approval_router.queue_for_approval(message_id=str(msg.id), conversation_id=str(conv.id), claim_level=3)
    approval_router.reject(req, actor=AdminUserFactory(), reason="off-message")
    msg.refresh_from_db()
    assert msg.governance_status == GovernanceStatus.BLOCKED


def test_edit_applies_new_body():
    conv, msg = _held_message()
    req = approval_router.queue_for_approval(message_id=str(msg.id), conversation_id=str(conv.id), claim_level=3)
    approval_router.edit(req, actor=AdminUserFactory(), new_body="approved wording")
    msg.refresh_from_db()
    assert msg.body == "approved wording"
    assert msg.governance_status == GovernanceStatus.APPROVED


def test_queue_is_idempotent():
    conv, msg = _held_message()
    r1 = approval_router.queue_for_approval(message_id=str(msg.id), conversation_id=str(conv.id), claim_level=3)
    r2 = approval_router.queue_for_approval(message_id=str(msg.id), conversation_id=str(conv.id), claim_level=3)
    assert r1.id == r2.id
