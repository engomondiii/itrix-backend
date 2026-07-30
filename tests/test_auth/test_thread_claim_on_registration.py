"""
THE VISITOR'S WORK FOLLOWS THEM IN (Architecture v2.9 R65).

Somebody who typed three paragraphs, decided they wanted to keep them, and signed up, keeps
them. It is the same `claim_threads()` call the invite path makes, with the same privacy
boundaries: never across sessions, never linking two anonymous sessions to each other.
"""

from __future__ import annotations

import pytest

from apps.clients.services.registration import register_client
from apps.conversations.models import Thread, ThreadOwnerKind

pytestmark = pytest.mark.django_db

ASSENT = [
    {"slug": "terms", "version": "1.2", "effective": "2026-07-30"},
    {"slug": "privacy", "version": "1.2", "effective": "2026-07-30"},
]


def _register(session=""):
    return register_client(
        email="keeper@example.com",
        password="a-long-enough-password",
        full_name="A Keeper",
        organization="An Organisation",
        assent_versions=ASSENT,
        visitor_session=session,
    )


def test_anonymous_threads_in_this_session_are_claimed():
    thread = Thread.objects.create(
        visitor_session="session-abc", owner_kind=ThreadOwnerKind.SESSION
    )
    outcome = _register(session="session-abc")

    thread.refresh_from_db()
    assert thread.client_id == outcome.client.id
    assert thread.owner_kind == ThreadOwnerKind.CLIENT
    assert thread.claimed_at is not None
    # The anonymous retention window no longer applies; leaving it set would delete a
    # paying customer's history.
    assert thread.retention_expires_at is None


def test_a_thread_from_another_session_is_never_claimed():
    """A boundary, not an optimisation: linking sessions would build the cross-visit profile
    the platform promises not to keep."""
    other = Thread.objects.create(
        visitor_session="somebody-else", owner_kind=ThreadOwnerKind.SESSION
    )
    _register(session="session-abc")
    other.refresh_from_db()
    assert other.client_id is None
    assert other.owner_kind == ThreadOwnerKind.SESSION


def test_registering_with_no_session_is_normal_and_not_an_error():
    outcome = _register(session="")
    assert outcome.created is True
