"""Session-bound, one-time access to personalized client reviews.

A URL carries only a short-lived opaque exchange code. The code is bound to the
browser session (or authenticated client) that requested the review and may be
consumed once. Successful exchange creates a second opaque token intended only for
an httpOnly BFF cookie; the review URL never contains a durable bearer credential,
lead UUID, journey state, score, or disclosure metadata.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.result_page.models import ClientPageAccessGrant, ClientPageAccessSession


class ClientPageAccessError(Exception):
    """Generic access failure. Caller must not reveal which check failed."""


def _hash(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _session_binding(visitor_session: str) -> str:
    return _hash(f"visitor:{visitor_session}") if visitor_session else ""


def issue_for_lead(
    lead, *, thread=None, visitor_session: str = "", client=None, ttl_seconds: int = 15 * 60
) -> str:
    """Return a short-lived opaque one-time code bound to the intended browser/client."""
    if thread is not None:
        visitor_session = str(getattr(thread, "visitor_session", "") or visitor_session or "")
        thread_client = getattr(thread, "client", None)
        client = thread_client or client
    client_id = str(getattr(client, "id", "") or "")
    code = secrets.token_urlsafe(32)
    now = timezone.now()
    with transaction.atomic():
        # A newer handoff supersedes any still-live code for this lead/binding.
        ClientPageAccessGrant.objects.filter(
            lead=lead, consumed_at__isnull=True, revoked_at__isnull=True
        ).update(revoked_at=now)
        ClientPageAccessGrant.objects.create(
            lead=lead,
            code_hash=_hash(code),
            visitor_session_hash=_session_binding(visitor_session),
            client_id=client_id,
            expires_at=now + timedelta(seconds=max(60, int(ttl_seconds))),
        )
    return code


@transaction.atomic
def exchange(code: str, *, visitor_session: str = "", client=None, session_ttl_seconds: int = 2 * 60 * 60):
    """Consume one exchange code and return ``(raw_session_token, lead)``."""
    now = timezone.now()
    grant = (
        ClientPageAccessGrant.objects.select_for_update()
        .select_related("lead")
        .filter(code_hash=_hash(code or ""))
        .first()
    )
    if grant is None or grant.revoked_at or grant.consumed_at or grant.expires_at <= now:
        raise ClientPageAccessError("access_unavailable")

    supplied_client_id = str(getattr(client, "id", "") or "")
    if grant.client_id:
        if not supplied_client_id or supplied_client_id != grant.client_id:
            raise ClientPageAccessError("access_unavailable")
    elif grant.visitor_session_hash:
        if not visitor_session or _session_binding(visitor_session) != grant.visitor_session_hash:
            raise ClientPageAccessError("access_unavailable")
    else:
        # Fail closed: new grants should always have one binding.
        raise ClientPageAccessError("access_unavailable")

    grant.consumed_at = now
    grant.save(update_fields=["consumed_at", "updated_at"])

    raw = secrets.token_urlsafe(40)
    ClientPageAccessSession.objects.filter(grant__lead=grant.lead, revoked_at__isnull=True).update(
        revoked_at=now
    )
    ClientPageAccessSession.objects.create(
        grant=grant,
        token_hash=_hash(raw),
        expires_at=now + timedelta(seconds=max(300, int(session_ttl_seconds))),
        last_seen_at=now,
    )
    return raw, grant.lead


def resolve_session(raw_token: str, *, visitor_session: str = "", client=None):
    """Return the authorized lead for a live access session, else raise generically."""
    now = timezone.now()
    session = (
        ClientPageAccessSession.objects.select_related("grant__lead")
        .filter(token_hash=_hash(raw_token or ""), revoked_at__isnull=True)
        .first()
    )
    if session is None or session.expires_at <= now:
        raise ClientPageAccessError("access_unavailable")
    grant = session.grant
    supplied_client_id = str(getattr(client, "id", "") or "")
    if grant.client_id:
        if not supplied_client_id or supplied_client_id != grant.client_id:
            raise ClientPageAccessError("access_unavailable")
    elif grant.visitor_session_hash:
        if not visitor_session or _session_binding(visitor_session) != grant.visitor_session_hash:
            raise ClientPageAccessError("access_unavailable")
    else:
        raise ClientPageAccessError("access_unavailable")

    # Avoid a write on every poll; update at most once per minute.
    if not session.last_seen_at or (now - session.last_seen_at).total_seconds() >= 60:
        ClientPageAccessSession.objects.filter(pk=session.pk).update(last_seen_at=now)
    return grant.lead
