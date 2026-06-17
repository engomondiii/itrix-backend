"""
Notification dispatcher.

Abstraction point for *delivering* notifications beyond storing them in-app (e.g. push,
Slack, websockets in future). In Phase 3 it logs and is a no-op beyond the DB record, so
the in-app tray works immediately; real channels can be added behind this seam without
touching callers.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("itrix")


def dispatch(notification) -> None:
    """Deliver a notification through any configured side channels (currently none)."""
    logger.info("Notification dispatched: %s — %s", notification.kind, notification.title)


def mark_read(notification) -> None:
    if not notification.read:
        notification.read = True
        notification.save(update_fields=["read", "updated_at"])
