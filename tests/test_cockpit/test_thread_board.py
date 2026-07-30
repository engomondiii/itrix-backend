"""
The thread board — ROW-LEVEL (Backend v7.1 §Phase 1, Surface 2 v7.0 §06).

── ANONYMOUS THREADS ARE REQUIRED, NOT OPTIONAL ────────────────────────────
The convenient implementation joins on Lead and therefore shows only threads with one
attached — which hides exactly the conversations oversight needs most. First-visit
conversations, where a visitor is describing a problem and nobody has decided anything
yet, are where a governance halt or a badly-chosen question does the most damage. They are
also the ones with no Lead.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def _visitor_turn(thread, body: str = "Our solver is slow.", seq: int = 1):
    """
    A visitor turn on ``thread``.

    ``Message.conversation`` is NOT NULL, so a bare ``Message.objects.create(thread=...)``
    fails at the database. The Thread the service reads and the Conversation the Message
    requires are two different models in this schema — a distinction easy to miss until the
    integrity error, which is exactly why this helper exists in one place.
    """
    from apps.conversations.models import Message, SenderKind
    from tests.factories.conversation_factory import ConversationFactory

    conversation = thread.conversation or ConversationFactory(lead=thread.lead)
    if thread.conversation_id != conversation.id:
        thread.conversation = conversation
        thread.save(update_fields=["conversation"])

    return Message.objects.create(
        conversation=conversation,
        thread=thread,
        sender_kind=SenderKind.VISITOR,
        body=body,
        seq=seq,
    )


def _team_client(role: str = "ASSESSMENT"):
    from django.contrib.auth import get_user_model
    from rest_framework.test import APIClient

    User = get_user_model()
    user = User.objects.create_user(
        email=f"{role.lower()}-board@itrix.test",
        password="a-long-enough-password",
        role=role,
        is_active=True,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_the_board_includes_anonymous_threads_and_labels_them():
    from apps.conversations.services import threads as thread_svc

    thread = thread_svc.create_thread(visitor_session="sess-anon-board")

    body = _team_client().get("/api/v1/cockpit/threads/").json()
    row = next((r for r in body["results"] if r["threadId"] == str(thread.id)), None)

    assert row is not None, "an anonymous thread must appear on the board"
    assert row["anonymous"] is True
    assert row["leadId"] is None


def test_the_board_never_infers_a_company():
    """
    An inferred company shown to an operator becomes an inferred company said out loud to
    the visitor. ``company`` comes from the Client record or is empty.
    """
    from apps.conversations.services import threads as thread_svc

    thread_svc.create_thread(visitor_session="sess-no-company")
    body = _team_client().get("/api/v1/cockpit/threads/").json()
    for row in body["results"]:
        if row["anonymous"]:
            assert row["company"] == ""


def test_the_row_reports_working_on_the_first_visitor_turn():
    """
    The same threshold ``shell_mode`` uses, restated as data rather than duplicated as
    logic: a thread with a visitor turn is one the visitor is working in.
    """
    from apps.conversations.services import threads as thread_svc

    quiet = thread_svc.create_thread(visitor_session="sess-quiet")
    spoken = thread_svc.create_thread(visitor_session="sess-spoken")
    _visitor_turn(spoken)

    rows = {r["threadId"]: r for r in _team_client().get("/api/v1/cockpit/threads/").json()["results"]}
    assert rows[str(quiet.id)]["working"] is False
    assert rows[str(spoken.id)]["working"] is True
    assert rows[str(spoken.id)]["visitorTurns"] == 1


def test_thread_detail_carries_the_internal_overlay():
    """
    Governance status, claim level and cited chunk ids. None of it reaches the visitor's
    plane; all of it is what makes the page oversight rather than a transcript viewer.
    """
    from apps.conversations.models import Message, SenderKind
    from apps.conversations.services import threads as thread_svc
    from tests.factories.conversation_factory import ConversationFactory

    thread = thread_svc.create_thread(visitor_session="sess-detail")
    conversation = thread.conversation or ConversationFactory(lead=thread.lead)
    thread.conversation = conversation
    thread.save(update_fields=["conversation"])
    Message.objects.create(
        conversation=conversation, thread=thread,
        sender_kind=SenderKind.AGENT, body="Here is what we heard.", seq=1,
        governance_status="approved", claim_level=2, cited_chunk_ids=["chunk-1"],
    )

    body = _team_client().get(f"/api/v1/cockpit/threads/{thread.id}/").json()
    turn = body["turns"][0]
    assert turn["governanceStatus"] == "approved"
    assert turn["claimLevel"] == 2
    assert turn["citedChunkIds"] == ["chunk-1"]


def test_thread_detail_declares_the_phase_two_keys_as_empty_not_absent():
    """
    An absent key makes the frontend guess whether it failed or there is nothing there. An
    empty list is honest, and it means the dashboard can render the panels without a second
    contract change when Phase 2 fills them.
    """
    from apps.conversations.services import threads as thread_svc

    thread = thread_svc.create_thread(visitor_session="sess-phase2-keys")
    body = _team_client().get(f"/api/v1/cockpit/threads/{thread.id}/").json()
    assert body["coverage"] is None
    assert body["attachments"] == []


def test_an_unknown_thread_is_404_not_500():
    import uuid

    response = _team_client().get(f"/api/v1/cockpit/threads/{uuid.uuid4()}/")
    assert response.status_code == 404


def test_a_junk_limit_does_not_become_a_500():
    response = _team_client().get("/api/v1/cockpit/threads/?limit=not-a-number")
    assert response.status_code == 200
