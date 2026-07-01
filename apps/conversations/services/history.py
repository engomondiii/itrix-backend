"""
Conversation history helpers.

Get-or-create the thread for a given context + subject, and read back the deliverable
message history (client-facing views never see held/blocked drafts). Keeping this in one
place means the review-chat, client-page-chat, and portal all resolve the same thread
deterministically.
"""

from __future__ import annotations

from django.utils import timezone

from apps.conversations.models import (
    Conversation,
    ConversationContext,
    Message,
    Participant,
    SenderKind,
)


def get_or_create_review_conversation(*, review_session_id: str, lead=None) -> Conversation:
    """The single review-chat thread for a session (keyed by session id, linked to lead)."""
    conv = Conversation.objects.filter(
        context=ConversationContext.REVIEW, review_session_id=str(review_session_id)
    ).first()
    if conv:
        if lead and conv.lead_id is None:
            conv.lead = lead
            conv.save(update_fields=["lead", "updated_at"])
        return conv
    return Conversation.objects.create(
        context=ConversationContext.REVIEW,
        review_session_id=str(review_session_id),
        lead=lead,
        title="Review chat",
    )


def get_or_create_client_page_conversation(lead) -> Conversation:
    """The client-page chat thread for a lead."""
    conv = Conversation.objects.filter(
        context=ConversationContext.CLIENT_PAGE, lead=lead
    ).first()
    if conv:
        return conv
    return Conversation.objects.create(
        context=ConversationContext.CLIENT_PAGE,
        lead=lead,
        review_session_id=str(getattr(lead, "review_session_id", "") or ""),
        title="Client page chat",
    )


def get_or_create_portal_conversation(client) -> Conversation:
    """The primary portal thread for a client."""
    conv = Conversation.objects.filter(
        context=ConversationContext.PORTAL, client=client
    ).first()
    if conv:
        return conv
    return Conversation.objects.create(
        context=ConversationContext.PORTAL,
        client=client,
        lead=client.lead,
        title="Portal conversation",
    )


def deliverable_messages(conversation: Conversation):
    """Client-facing message list: only approved/auto-approved turns, in order."""
    from apps.conversations.models import GovernanceStatus

    return conversation.messages.filter(
        governance_status__in=[
            GovernanceStatus.AUTO_APPROVED,
            GovernanceStatus.APPROVED,
        ]
    ).order_by("created_at")


def all_messages(conversation: Conversation):
    """Full message list (team/console view — includes held drafts)."""
    return conversation.messages.order_by("created_at")


def touch(conversation: Conversation) -> None:
    conversation.last_message_at = timezone.now()
    conversation.save(update_fields=["last_message_at", "updated_at"])


def upsert_participant(conversation: Conversation, *, kind: str, client=None, user=None, display_name: str = "") -> Participant:
    part, _created = Participant.objects.get_or_create(
        conversation=conversation,
        kind=kind,
        client=client,
        user=user,
        defaults={"display_name": display_name},
    )
    return part


def mark_read(conversation: Conversation, *, client=None, user=None) -> None:
    for part in conversation.participants.filter(client=client, user=user):
        part.last_read_at = timezone.now()
        part.save(update_fields=["last_read_at", "updated_at"])


def unread_count(conversation: Conversation, *, client=None, user=None) -> int:
    """Deliverable messages after the participant's last_read_at."""
    part = conversation.participants.filter(client=client, user=user).first()
    qs = deliverable_messages(conversation)
    if part and part.last_read_at:
        qs = qs.filter(created_at__gt=part.last_read_at)
    # Don't count the participant's own messages as unread.
    if client is not None:
        qs = qs.exclude(sender_kind=SenderKind.CLIENT, sender_client=client)
    return qs.count()
