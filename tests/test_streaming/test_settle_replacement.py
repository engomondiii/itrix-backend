"""
Streaming governance Part 3 — settle (Backend v6.0 §6.3).

A message that streamed cleanly but FAILS the settle gate is replaced by the approved
under-review wording. Provisional text is always replaceable and is never treated as
delivered.
"""

from __future__ import annotations

import pytest

from apps.conversations.models import Message, StreamingStatus
from apps.conversations.services import ingest, threads as thread_svc

pytestmark = pytest.mark.django_db


def _thread():
    return thread_svc.create_thread(visitor_session="sess-settle")


def test_a_held_message_never_exposes_its_body():
    thread = _thread()
    message = ingest.ingest_agent_message(
        thread.conversation,
        agent_key="concierge",
        body="Draft that did not clear governance",
        governance_status="pending",
        thread=thread,
        streaming_status=StreamingStatus.UNDER_REVIEW,
    )
    from apps.conversations.serializers_thread import ThreadTurnSerializer

    data = ThreadTurnSerializer(message).data
    assert data["body"] == ""
    assert data["underReview"] is True


def test_a_halted_message_stays_empty_on_history_fetch():
    """
    Its partial text was discarded from the client ON PURPOSE. If it reappeared on a
    history fetch the halt would have achieved nothing.
    """
    thread = _thread()
    message = ingest.ingest_agent_message(
        thread.conversation,
        agent_key="concierge",
        body="Alpha is 30% faster",
        governance_status="auto_approved",
        thread=thread,
        streaming_status=StreamingStatus.HALTED,
    )
    from apps.conversations.serializers_thread import ThreadTurnSerializer

    assert ThreadTurnSerializer(message).data["body"] == ""


def test_halted_messages_are_excluded_from_resume():
    """Replaying a halt on reconnect would deliver exactly the text the guard stopped."""
    from apps.realtime.services.sequence import resume_payload

    thread = _thread()
    ingest.ingest_inbound(thread.conversation, sender_kind="visitor", body="hello", thread=thread)
    ingest.ingest_agent_message(
        thread.conversation,
        agent_key="concierge",
        body="Alpha is 30% faster",
        thread=thread,
        streaming_status=StreamingStatus.HALTED,
    )
    payload = resume_payload(thread, 0)
    bodies = [m["body"] for m in payload["messages"]]
    assert "Alpha is 30% faster" not in bodies


def test_context_note_is_persisted_when_content_could_not_be_considered():
    thread = _thread()
    note = "This conversation is long enough that some earlier turns could not be included."
    message = ingest.ingest_agent_message(
        thread.conversation,
        agent_key="concierge",
        body="Here is what I can tell you.",
        thread=thread,
        context_note=note,
    )
    assert Message.objects.get(id=message.id).context_note == note
