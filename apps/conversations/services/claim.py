"""
Thread claim on signup (Backend v6.0 §2.2).

When an anonymous visitor creates a workspace, the threads they built while anonymous
must follow them — every turn, artifact and attachment preserved. Otherwise the visitor
loses the conversation they came to have, which is the one thing v2.6 promises will
never happen.

── ORDERING IS THE SECURITY PROPERTY ────────────────────────────────────────
The claim runs INSIDE the same transaction as the single-use nonce burn, and AFTER it:

    consume_nonce()            # invariant 1 — burn BEFORE anything can return a subject
      -> create_or_bind_client()
      -> claim_threads(session -> client)
      -> clear retention_expires_at
      -> emit thread.updated

If the claim ran before the burn, a replayed invite token would re-run the claim. If it
ran outside the transaction, a failure after the burn would strand the visitor's threads
on a session they can no longer prove they own. Both are why this is one atomic block
rather than two convenient steps.

── TWO PRIVACY BOUNDARIES ───────────────────────────────────────────────────
* A claim NEVER merges threads across sessions.
* A claim NEVER links two anonymous sessions to each other.

These are boundaries, not optimisations: linking sessions would build exactly the
cross-visit profile the platform promises not to keep.
"""

from __future__ import annotations

import logging

from django.db import transaction

from apps.conversations.models import (
    Conversation,
    Thread,
    ThreadOwnerKind,
    ThreadParticipant,
)

logger = logging.getLogger("itrix")


@transaction.atomic
def claim_threads(*, visitor_session: str, client, lead=None) -> list[Thread]:
    """
    Migrate every thread owned by ``visitor_session`` to ``client``.

    MUST be called inside the invite-claim transaction, AFTER the nonce burn. Returns
    the claimed threads (possibly empty — a visitor who never spoke has none, which is
    normal, not an error).
    """
    if not visitor_session or client is None:
        return []

    from django.utils import timezone

    threads = list(
        Thread.objects.select_for_update().filter(
            visitor_session=str(visitor_session),
            owner_kind=ThreadOwnerKind.SESSION,
            client__isnull=True,
        )
    )
    if not threads:
        return []

    now = timezone.now()
    claimed: list[Thread] = []
    for thread in threads:
        thread.client = client
        thread.owner_kind = ThreadOwnerKind.CLIENT
        thread.claimed_at = now
        # The anonymous retention window no longer applies — the client's contractual
        # retention takes over. Leaving it set would delete a paying customer's history.
        thread.retention_expires_at = None
        if lead is not None and thread.lead_id is None:
            thread.lead = lead
        thread.save(
            update_fields=[
                "client",
                "owner_kind",
                "claimed_at",
                "retention_expires_at",
                "lead",
                "updated_at",
            ]
        )

        # Carry the transport-level Conversation across too, so the shipped realtime
        # layer resolves the same thread for the now-authenticated client.
        if thread.conversation_id:
            Conversation.objects.filter(id=thread.conversation_id).update(
                client=client, lead=thread.lead_id
            )

        ThreadParticipant.objects.get_or_create(
            thread=thread,
            principal_kind=ThreadParticipant.PrincipalKind.CLIENT,
            principal_id=str(client.id),
            defaults={"role": ThreadParticipant.Role.VISITOR},
        )
        claimed.append(thread)

    logger.info(
        "thread.claim %s thread(s) migrated from session to client %s",
        len(claimed),
        client.id,
    )

    # Announce on the next commit so a rolled-back claim never emits a phantom event.
    transaction.on_commit(lambda: _emit_thread_updated(claimed))
    return claimed


def _emit_thread_updated(threads: list[Thread]) -> None:
    """Push ``thread.updated`` for each claimed thread. Best-effort."""
    try:
        from apps.conversations.services.fan_out import broadcast_thread_updated

        for thread in threads:
            broadcast_thread_updated(thread)
    except Exception:  # noqa: BLE001 - realtime is optional
        logger.debug("thread.updated emit skipped (realtime unavailable)")
