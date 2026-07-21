"""
"What changed since you were last here" (Playbook §12E).

    Work we completed, issues we resolved, updates we shipped, and anything waiting on
    a decision from you.

The last clause is the one that makes this honest. A digest reporting only our own
completed work is a progress report — it hides the item the customer most needs to see,
which is the one WE are waiting on THEM for.

Empty state is a real state: "Nothing has changed since your last visit." is better than
padding the list with activity that is not change.
"""

from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger("itrix")

EMPTY_STATE = "Nothing has changed since your last visit."


def record(client, *, kind: str, title: str, detail: str = "", occurred_at=None):
    from apps.customer_success.models import ChangeLogEntry

    return ChangeLogEntry.objects.create(
        client=client,
        kind=kind,
        title=title[:300],
        detail=detail,
        occurred_at=occurred_at or timezone.now(),
    )


def build(client, *, since=None, limit: int = 50) -> dict:
    """
    Build the digest.

    ``since`` defaults to the client's last login, which is the honest definition of
    "since you were last here" — not "since we last generated a digest".
    """
    from apps.customer_success.models import ChangeLogEntry

    if client is None:
        return {"since": None, "entries": [], "awaiting_decision": [], "empty_state": EMPTY_STATE}

    cutoff = since or getattr(client, "last_login_at", None)
    qs = ChangeLogEntry.objects.filter(client=client)
    if cutoff is not None:
        qs = qs.filter(occurred_at__gte=cutoff)
    entries = list(qs.order_by("-occurred_at")[:limit])

    awaiting = [e for e in entries if e.kind == ChangeLogEntry.Kind.AWAITING_DECISION]
    other = [e for e in entries if e.kind != ChangeLogEntry.Kind.AWAITING_DECISION]

    return {
        "since": cutoff.isoformat() if cutoff else None,
        # Items waiting on the customer are returned SEPARATELY and first. Mixing them
        # into a reverse-chronological list buries the one thing they must act on.
        "awaiting_decision": [_serialize(e) for e in awaiting],
        "entries": [_serialize(e) for e in other],
        "empty_state": EMPTY_STATE if not entries else "",
    }


def _serialize(entry) -> dict:
    return {
        "id": str(entry.id),
        "kind": entry.kind,
        "title": entry.title,
        "detail": entry.detail,
        "occurredAt": entry.occurred_at.isoformat(),
    }


def mark_surfaced(client, entries) -> None:
    """Stamp entries as seen so a later digest does not repeat them."""
    from apps.customer_success.models import ChangeLogEntry

    ids = [e["id"] for e in entries if isinstance(e, dict) and e.get("id")]
    if ids:
        ChangeLogEntry.objects.filter(client=client, id__in=ids).update(
            surfaced_at=timezone.now()
        )
