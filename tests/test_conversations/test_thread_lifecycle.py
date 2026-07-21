"""Thread creation, titling, renaming and retention (Backend v6.0 §2.1, §2.5)."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.conversations.models import Thread, ThreadOwnerKind
from apps.conversations.services import threads as thread_svc

pytestmark = pytest.mark.django_db


def test_anonymous_thread_gets_a_retention_expiry_at_creation():
    """
    Retention is set at CREATION, not by a sweep. An abandoned conversation expires on
    its own without anyone remembering to schedule it.
    """
    thread = thread_svc.create_thread(visitor_session="sess-1")
    assert thread.retention_expires_at is not None
    assert thread.retention_expires_at > timezone.now()
    assert thread.is_anonymous is True


def test_thread_creates_its_backing_conversation():
    thread = thread_svc.create_thread(visitor_session="sess-1")
    assert thread.conversation is not None
    assert thread.conversation.context == "anonymous_review"


def test_title_derives_from_the_visitors_own_words():
    thread = thread_svc.create_thread(visitor_session="sess-1")
    thread_svc.set_title_if_unset(
        thread, "Our HBM traffic is saturating the inference fleet during peak hours."
    )
    thread.refresh_from_db()
    assert "HBM" in thread.title
    assert len(thread.title) <= 80


def test_title_falls_back_rather_than_inventing():
    """Nothing meaningful to work with means the default — never a guess."""
    assert thread_svc.derive_title("") == thread_svc.DEFAULT_TITLE
    assert thread_svc.derive_title("   ") == thread_svc.DEFAULT_TITLE
    assert thread_svc.derive_title("the a of in") == thread_svc.DEFAULT_TITLE


def test_a_user_set_title_is_never_overwritten():
    thread = thread_svc.create_thread(visitor_session="sess-1")
    thread_svc.rename(thread, "My own name for this")
    thread_svc.set_title_if_unset(thread, "Some later message that would retitle it")
    thread.refresh_from_db()
    assert thread.title == "My own name for this"
    assert thread.title_source == "user"


def test_session_isolation_is_enforced_in_the_query():
    """
    An anonymous session can only ever see threads it owns. This is filtered in the
    QUERY — a serializer-level filter would be one refactor from leaking.
    """
    mine = thread_svc.create_thread(visitor_session="sess-mine")
    thread_svc.create_thread(visitor_session="sess-theirs")

    listed = list(thread_svc.list_for_session("sess-mine"))
    assert [t.id for t in listed] == [mine.id]

    assert thread_svc.get_for_session(mine.id, "sess-theirs") is None
    assert thread_svc.get_for_session(mine.id, "sess-mine") is not None


def test_empty_session_lists_nothing():
    thread_svc.create_thread(visitor_session="sess-1")
    assert list(thread_svc.list_for_session("")) == []


def test_expired_anonymous_threads_are_purged():
    thread = thread_svc.create_thread(visitor_session="sess-1")
    Thread.objects.filter(id=thread.id).update(
        retention_expires_at=timezone.now() - timezone.timedelta(days=1)
    )
    assert thread_svc.purge_expired_anonymous_threads() == 1
    assert not Thread.objects.filter(id=thread.id).exists()


def test_claimed_threads_are_never_purged():
    """The client's contractual retention takes over — a paying customer keeps history."""
    thread = thread_svc.create_thread(visitor_session="sess-1")
    Thread.objects.filter(id=thread.id).update(
        retention_expires_at=timezone.now() - timezone.timedelta(days=1),
        claimed_at=timezone.now(),
        owner_kind=ThreadOwnerKind.CLIENT,
    )
    assert thread_svc.purge_expired_anonymous_threads() == 0
    assert Thread.objects.filter(id=thread.id).exists()
