from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.agents.services.output_contract import AgentOutput
from apps.conversations.models import Message
from apps.conversations.services import threads as thread_svc
from apps.conversations.views_thread import _generate_assistant_turn

pytestmark = pytest.mark.django_db


def test_http_assistant_turn_persists_retrieved_chunk_ids():
    thread = thread_svc.create_thread(visitor_session="grounding-session", title="Grounding")
    output = AgentOutput(
        payload={"reply": "A grounded ALPHA Compute answer.", "canContinue": False},
        chunk_ids=["chunk-a", "chunk-b"],
        used_ai=True,
        claim_level=1,
    )

    with patch("apps.agents.services.concierge.ConciergeAgent.run", return_value=output):
        turn = _generate_assistant_turn(thread, "What is ALPHA Compute?")

    assert turn is not None
    saved = Message.objects.get(id=turn["id"])
    assert saved.cited_chunk_ids == ["chunk-a", "chunk-b"]
