"""Client-plane session invalidation boundaries.

Client JWTs are stateless, but every token carries ``Client.session_version``. Advancing
that monotonic generation is the authoritative revocation operation: access, refresh and
WS credentials minted before the change immediately fail their normal DB-backed session
check.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger("itrix")


def revoke_current_session(client) -> int:
    """Atomically revoke every credential in the client's current token generation.

    This is used by explicit logout. Database failure is intentionally allowed to
    propagate: a caller must never claim that revocation succeeded when the generation
    could not be durably advanced.
    """

    model = client.__class__
    with transaction.atomic():
        locked = model.objects.select_for_update().get(pk=client.pk)
        locked.session_version = int(getattr(locked, "session_version", 0) or 0) + 1
        locked.save(update_fields=["session_version", "updated_at"])
        generation = int(locked.session_version)

    # Keep the authenticated in-memory instance coherent for any code that observes it
    # later in the same request.
    client.session_version = generation
    logger.info("clients.session_revoked client=%s generation=%s", client.id, generation)
    return generation


def invalidate_other_sessions(client) -> None:
    """Invalidate prior sessions inside the transaction that writes a new password.

    Password change also records the time of the security event for audit/display. The
    monotonic generation remains the actual token-revocation boundary because JWT ``iat``
    is only second-resolution.
    """

    client.password_changed_at = timezone.now()
    client.session_version = int(getattr(client, "session_version", 0) or 0) + 1
    client.save(update_fields=["password_changed_at", "session_version", "updated_at"])
    logger.info("clients.sessions_invalidated client=%s", client.id)
