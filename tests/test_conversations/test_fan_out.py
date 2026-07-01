"""Governed fan-out: deliverable vs under-review; realtime-off no-op."""

from __future__ import annotations

import pytest

from apps.conversations.models import GovernanceStatus
from apps.conversations.services import fan_out, ingest
from apps.conversations.services.history import get_or_create_review_conversation
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def test_broadcast_is_noop_when_realtime_off(settings):
    settings.ENABLE_REALTIME = False
    lead = LeadFactory()
    conv = get_or_create_review_conversation(review_session_id="s", lead=lead)
    msg = ingest.ingest_inbound(conv, sender_kind="visitor", body="hi")
    # Should not raise even though no channel layer is configured for delivery.
    fan_out.broadcast_message(msg)


def test_deliverable_flag_drives_broadcast_shape():
    lead = LeadFactory()
    conv = get_or_create_review_conversation(review_session_id="s", lead=lead)
    approved = ingest.ingest_agent_message(conv, agent_key="concierge", body="ok", governance_status=GovernanceStatus.AUTO_APPROVED)
    held = ingest.ingest_agent_message(conv, agent_key="concierge", body="secret", governance_status=GovernanceStatus.PENDING)
    assert approved.is_deliverable is True
    assert held.is_deliverable is False
