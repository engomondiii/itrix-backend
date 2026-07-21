"""
Thread lifecycle (Backend v6.0 §2.1, §2.2, §2.5).

Create, list, title, rename and retire threads. Everything a caller needs to give a
visitor a persistent conversation from their very first sentence.

── THE RULES THIS MODULE ENFORCES ───────────────────────────────────────────
1. A thread created by an unidentified visitor is owned by the SIGNED VISITOR SESSION,
   listed ONLY to that session, and carries a retention expiry.
2. ``list_for_session`` and ``list_for_client`` never cross. An anonymous session can
   only ever see threads it owns — enforced in the QUERY, not in the serializer.
3. A generated title inherits the NO-INFERENCE rule: a title is visitor-visible, so it
   may never name an inferred company, department or persona (§2.5).
4. Retention is set at creation, not by a sweep. A thread that is never claimed expires
   on its own without anyone remembering to schedule it.
"""

from __future__ import annotations

import logging
import re

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.conversations.models import (
    Conversation,
    ConversationContext,
    Thread,
    ThreadContext,
    ThreadOwnerKind,
    ThreadParticipant,
    ThreadTitleSource,
)

logger = logging.getLogger("itrix")

# Conversation context (transport) for each thread context (spine).
_CONVERSATION_CONTEXT = {
    ThreadContext.ANONYMOUS_REVIEW.value: ConversationContext.ANONYMOUS_REVIEW,
    ThreadContext.REVIEW.value: ConversationContext.REVIEW,
    ThreadContext.CLIENT_PAGE.value: ConversationContext.CLIENT_PAGE,
    ThreadContext.PORTAL.value: ConversationContext.PORTAL,
    ThreadContext.CUSTOMER_SUCCESS.value: ConversationContext.CUSTOMER_SUCCESS,
}

DEFAULT_TITLE = "New review"


def anon_retention_days() -> int:
    return int(getattr(settings, "ANON_THREAD_RETENTION_DAYS", 90))


@transaction.atomic
def create_thread(
    *,
    visitor_session: str = "",
    client=None,
    lead=None,
    context: str = ThreadContext.ANONYMOUS_REVIEW,
    title: str = "",
    state_at_creation: str = "ARRIVED",
) -> Thread:
    """
    Create a thread and its backing Conversation.

    An anonymous thread (``visitor_session`` with no client) gets a retention expiry
    immediately, so an abandoned conversation cleans itself up without any operator
    remembering to schedule it.
    """
    owner_kind = ThreadOwnerKind.CLIENT if client is not None else ThreadOwnerKind.SESSION

    retention_expires_at = None
    if client is None:
        retention_expires_at = timezone.now() + timezone.timedelta(days=anon_retention_days())

    thread = Thread.objects.create(
        owner_kind=owner_kind,
        visitor_session=str(visitor_session or ""),
        client=client,
        lead=lead,
        context=context,
        title=(title or "").strip()[:200],
        title_source=ThreadTitleSource.GENERATED,
        state_at_creation=state_at_creation,
        last_activity_at=timezone.now(),
        retention_expires_at=retention_expires_at,
    )

    conversation = Conversation.objects.create(
        context=_CONVERSATION_CONTEXT.get(context, ConversationContext.REVIEW),
        lead=lead,
        client=client,
        review_session_id=str(visitor_session or ""),
        title=thread.title or DEFAULT_TITLE,
        last_message_at=timezone.now(),
    )
    thread.conversation = conversation
    thread.save(update_fields=["conversation", "updated_at"])

    if visitor_session:
        ThreadParticipant.objects.get_or_create(
            thread=thread,
            principal_kind=ThreadParticipant.PrincipalKind.SESSION,
            principal_id=str(visitor_session),
            defaults={"role": ThreadParticipant.Role.VISITOR},
        )
    if client is not None:
        ThreadParticipant.objects.get_or_create(
            thread=thread,
            principal_kind=ThreadParticipant.PrincipalKind.CLIENT,
            principal_id=str(client.id),
            defaults={"role": ThreadParticipant.Role.VISITOR},
        )

    logger.info("thread.create %s owner=%s context=%s", thread.id, owner_kind, context)
    return thread


def list_for_session(visitor_session: str):
    """
    Threads owned by this anonymous session — and ONLY this session.

    The isolation is in the QUERY. A serializer-level filter would be one refactor away
    from leaking another visitor's conversation list.
    """
    if not visitor_session:
        return Thread.objects.none()
    return Thread.objects.filter(
        visitor_session=str(visitor_session),
        owner_kind=ThreadOwnerKind.SESSION,
        client__isnull=True,
    ).order_by("-last_activity_at", "-created_at")


def list_for_client(client):
    """Threads owned by this client (including any claimed from an anonymous session)."""
    if client is None:
        return Thread.objects.none()
    return Thread.objects.filter(client=client).order_by("-last_activity_at", "-created_at")


def get_for_session(thread_id, visitor_session: str) -> Thread | None:
    """Fetch one thread, scoped to the owning session. Returns None rather than raising."""
    if not visitor_session:
        return None
    return (
        Thread.objects.filter(
            id=thread_id,
            visitor_session=str(visitor_session),
            owner_kind=ThreadOwnerKind.SESSION,
            client__isnull=True,
        )
        .select_related("conversation", "lead")
        .first()
    )


def get_for_client(thread_id, client) -> Thread | None:
    """Fetch one thread, scoped to the owning client."""
    if client is None:
        return None
    return (
        Thread.objects.filter(id=thread_id, client=client)
        .select_related("conversation", "lead")
        .first()
    )


def touch(thread: Thread) -> None:
    """Mark activity. Cheap, called on every turn."""
    thread.last_activity_at = timezone.now()
    thread.save(update_fields=["last_activity_at", "updated_at"])
    if thread.conversation_id:
        Conversation.objects.filter(id=thread.conversation_id).update(
            last_message_at=thread.last_activity_at
        )


# ─────────────────────────────────────────────────────────────────────────────
# Titling (§2.5)
# ─────────────────────────────────────────────────────────────────────────────
# A title is VISITOR-VISIBLE, so it inherits the no-inference rule: it may never name an
# inferred company, department or persona. Phase 1 derives the title DETERMINISTICALLY
# from the visitor's own first sentence — their words, never our guess. The low-temperature
# generated title arrives with Phase 2 behind ENABLE_ADAPTIVE_QUESTIONS, bound to
# Claim-Card level 1.

_TITLE_STOPWORDS = {
    "our", "the", "a", "an", "we", "i", "is", "are", "and", "to", "of", "in",
    "on", "for", "it", "that", "this", "with", "as", "at", "by", "be", "been",
}


def derive_title(first_message: str) -> str:
    """
    A short, honest title built from the visitor's own words.

    Deterministic by design: no model call, no inference, nothing to review. Returns
    ``DEFAULT_TITLE`` when there is nothing meaningful to work with rather than
    inventing something.
    """
    text = re.sub(r"\s+", " ", (first_message or "").strip())
    if not text:
        return DEFAULT_TITLE

    # First sentence, capped.
    first = re.split(r"(?<=[.!?])\s", text)[0]
    words = [w for w in first.split(" ") if w]
    kept: list[str] = []
    for word in words:
        kept.append(word)
        if len(" ".join(kept)) >= 60:
            break
    title = " ".join(kept).strip(" ,;:-")

    if not title or all(w.lower() in _TITLE_STOPWORDS for w in title.split()):
        return DEFAULT_TITLE
    if len(title) > 80:
        title = title[:77].rstrip() + "..."
    return title[:1].upper() + title[1:]


def set_title_if_unset(thread: Thread, first_message: str) -> Thread:
    """
    Title the thread from its first exchange, then FREEZE it.

    A user-set title is never overwritten — ``title_source`` is the guard, so a later
    turn cannot silently rename a conversation the visitor already named.
    """
    if thread.title_source == ThreadTitleSource.USER:
        return thread
    if thread.title and thread.title != DEFAULT_TITLE:
        return thread
    thread.title = derive_title(first_message)
    thread.save(update_fields=["title", "updated_at"])
    if thread.conversation_id:
        Conversation.objects.filter(id=thread.conversation_id).update(title=thread.title)
    return thread


def rename(thread: Thread, title: str) -> Thread:
    """Rename a thread on the visitor's instruction. Marks the title as user-owned."""
    cleaned = re.sub(r"\s+", " ", (title or "").strip())[:200]
    if not cleaned:
        return thread
    thread.title = cleaned
    thread.title_source = ThreadTitleSource.USER
    thread.save(update_fields=["title", "title_source", "updated_at"])
    if thread.conversation_id:
        Conversation.objects.filter(id=thread.conversation_id).update(title=cleaned)
    return thread


# ─────────────────────────────────────────────────────────────────────────────
# Retention
# ─────────────────────────────────────────────────────────────────────────────
def expired_anonymous_threads():
    """Anonymous threads whose retention window has closed."""
    return Thread.objects.filter(
        owner_kind=ThreadOwnerKind.SESSION,
        client__isnull=True,
        claimed_at__isnull=True,
        retention_expires_at__lt=timezone.now(),
    )


def purge_expired_anonymous_threads() -> int:
    """
    Delete expired anonymous threads and everything hanging off them.

    Returns the number purged. Cascades remove the messages; the Conversation row is
    removed explicitly because the FK is SET_NULL by design (a thread may outlive its
    transport grouping, but an expired thread should leave nothing behind).
    """
    count = 0
    for thread in expired_anonymous_threads().select_related("conversation").iterator():
        conversation_id = thread.conversation_id
        thread.delete()
        if conversation_id:
            Conversation.objects.filter(id=conversation_id).delete()
        count += 1
    if count:
        logger.info("thread.retention purged %s expired anonymous threads", count)
    return count
