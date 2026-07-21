"""Question-loop fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _enable(settings):
    settings.ENABLE_ADAPTIVE_QUESTIONS = True
    # Generation OFF by default: these tests assert the DETERMINISTIC layer, and a live
    # model call would make them non-reproducible.
    settings.ENABLE_AI_ENGINE = False


@pytest.fixture
def thread(db):
    from apps.conversations.services import threads as thread_svc

    return thread_svc.create_thread(visitor_session="sess-loop")


def add_turn(thread, body):
    from apps.conversations.services import ingest

    return ingest.ingest_inbound(
        thread.conversation, sender_kind="visitor", body=body, thread=thread
    )
