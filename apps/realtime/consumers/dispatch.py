"""
The ``ws/review/{segment}/`` dispatcher.

── WHY A DISPATCHER EXISTS ──────────────────────────────────────────────────
Backend v6.0 mounts the new anonymous thread consumer at ``ws/review/{thread_id}/``.
The shipped v4.0 build already serves ``ws/review/{session}/`` with the legacy
``ReviewConsumer``. Same path, two contracts.

Hard-cutting the route would break every currently-open review socket the moment this
deploys, including the client-page chat that the shipped frontend depends on. So this
dispatcher resolves the segment AT CONNECT TIME:

    segment resolves to a Thread owned by this session  ->  ThreadConsumer   (v6.0)
    otherwise                                           ->  ReviewConsumer   (v4.0)

Resolution is by DATA, not by feature flag, so a v6.0 client and a v4.0 client can share
the deployment during the migration window. When ENABLE_CONVERSATION_SURFACE is off, the
thread routes are not mounted, no threads exist, and every connection falls through to
the legacy consumer — which is exactly the reversible behaviour each phase promises.

This is a documented deviation from the letter of the spec (which lists
``consumers/review.py`` under ADDED). The spec assumes a greenfield route; the shipped
repo has one already. The dispatcher honours the spec's INTENT — a session-authenticated
anonymous thread consumer at that path — without breaking a live socket.
"""

from __future__ import annotations

import logging
import uuid as _uuid

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

logger = logging.getLogger("itrix")


class ReviewDispatchConsumer(AsyncJsonWebsocketConsumer):
    """
    Resolves ``ws/review/{segment}/`` to the right consumer and delegates to it.

    Implemented by DELEGATION rather than inheritance: both consumers own their own
    connect/receive lifecycle, and trying to merge them into one class hierarchy would
    couple the v4.0 contract to the v6.0 one permanently — the opposite of a migration.
    """

    async def connect(self):
        segment = self.scope["url_route"]["kwargs"].get("session") or ""
        session_id = _session_from_scope(self.scope)

        delegate_cls = await database_sync_to_async(_pick_consumer)(segment, session_id)

        # Re-key the URL kwargs to what the chosen consumer expects.
        scope = dict(self.scope)
        route = dict(scope.get("url_route") or {})
        kwargs = dict(route.get("kwargs") or {})
        if delegate_cls.__name__ == "ThreadConsumer":
            kwargs["thread_id"] = segment
        else:
            kwargs["session"] = segment
        route["kwargs"] = kwargs
        scope["url_route"] = route

        self._delegate = delegate_cls(scope=scope)
        # Hand over the channel plumbing so the delegate can send and join groups.
        self._delegate.channel_layer = self.channel_layer
        self._delegate.channel_name = self.channel_name
        self._delegate.channel_receive = getattr(self, "channel_receive", None)
        self._delegate.base_send = self.base_send
        self._delegate.scope = scope

        await self._delegate.connect()

    async def receive_json(self, content, **kwargs):
        delegate = getattr(self, "_delegate", None)
        if delegate is not None:
            await delegate.receive_json(content, **kwargs)

    async def receive(self, text_data=None, bytes_data=None, **kwargs):
        delegate = getattr(self, "_delegate", None)
        if delegate is not None:
            await delegate.receive(text_data=text_data, bytes_data=bytes_data, **kwargs)
            return
        await super().receive(text_data=text_data, bytes_data=bytes_data, **kwargs)

    async def disconnect(self, code):
        delegate = getattr(self, "_delegate", None)
        if delegate is not None:
            await delegate.disconnect(code)

    async def dispatch(self, message):
        """Forward channel-layer events (group sends) to the delegate."""
        delegate = getattr(self, "_delegate", None)
        if delegate is not None:
            await delegate.dispatch(message)
            return
        await super().dispatch(message)


def _pick_consumer(segment: str, session_id: str):
    """
    Choose the consumer for this segment.

    A Thread match requires BOTH a valid uuid AND ownership by the calling session, so a
    guessed thread id cannot route a stranger into someone else's thread — it falls
    through to the legacy consumer, which then applies its own checks.
    """
    from apps.realtime.consumers.review import ReviewConsumer

    try:
        _uuid.UUID(str(segment))
    except (ValueError, TypeError, AttributeError):
        return ReviewConsumer

    if not session_id:
        return ReviewConsumer

    try:
        from apps.conversations.services import threads as thread_svc

        if thread_svc.get_for_session(segment, session_id) is not None:
            from apps.realtime.consumers.thread import ThreadConsumer

            return ThreadConsumer
    except Exception:  # noqa: BLE001 - spine not migrated yet
        logger.debug("thread lookup failed during dispatch; using legacy consumer")
    return ReviewConsumer


def _session_from_scope(scope) -> str:
    for name, value in scope.get("headers", []):
        if name == b"cookie":
            for part in value.decode(errors="ignore").split(";"):
                key, _, val = part.strip().partition("=")
                if key == "itrix_visitor_session":
                    return val.strip()[:64]
    query = (scope.get("query_string") or b"").decode(errors="ignore")
    for pair in query.split("&"):
        key, _, val = pair.partition("=")
        if key == "session":
            return val.strip()[:64]
    return ""
