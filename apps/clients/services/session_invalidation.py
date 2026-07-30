"""
SESSION INVALIDATION ON A PASSWORD CHANGE (Backend v7.2 §15.3 property 3).

── HOW YOU INVALIDATE A STATELESS JWT ──────────────────────────────────────
You cannot revoke one. So the client plane compares the token's issue time against
`Client.password_changed_at`: a token minted before the last password change is refused by
`ClientJWTAuthentication`. Stamping the timestamp IS the invalidation.

That means the guarantee lives in two places and both are load-bearing — the stamp here,
and the check in the authentication class. A test asserts the pair, because either one
alone is silently useless.

── AND THE RESPONSE SAYS IT HAPPENED ───────────────────────────────────────
Being signed out of another device without being told reads as a fault. Being told reads
as a security feature the person can watch work, which is why the copy names it
(Playbook v1.9 §18E).
"""

from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger("itrix")


def invalidate_other_sessions(client) -> None:
    """
    Stamp ``password_changed_at``, which invalidates every previously minted token.

    Called inside the transaction that writes the new password, so a rolled-back password
    change does not leave a customer mysteriously signed out everywhere.
    """
    client.password_changed_at = timezone.now()
    client.save(update_fields=["password_changed_at", "updated_at"])
    logger.info("clients.sessions_invalidated client=%s", client.id)
