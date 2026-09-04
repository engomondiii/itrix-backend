"""
Realtime WebSocket URL routes.

    ws/review/{session}/       ReviewConsumer       (PUBLIC, session-scoped)
    ws/portal/                 PortalConsumer       (CLIENT plane, client-JWT/ticket)
    ws/console/                TeamConsoleConsumer  (TEAM plane, team-JWT)

Mounted by the top-level itrix/routing.py behind the ws_auth middleware stack.

The historical ``ws/client-page/{token}/`` bearer route is deliberately retired. My
Review uses the tokenless HTTP/BFF access-session flow; its opaque access credential is
kept in an httpOnly cookie and is never exposed to browser JavaScript for a WebSocket.
"""

from __future__ import annotations

from django.urls import path

from apps.realtime.consumers.dispatch import ReviewDispatchConsumer
from apps.realtime.consumers.portal import PortalConsumer
from apps.realtime.consumers.review import ReviewConsumer  # noqa: F401
from apps.realtime.consumers.team_console import TeamConsoleConsumer

websocket_urlpatterns = [
    # v6.0: the segment is resolved at connect time — a Thread owned by the calling
    # session routes to ThreadConsumer, anything else falls through to the shipped
    # ReviewConsumer. See apps/realtime/consumers/dispatch.py for why.
    path("ws/review/<str:session>/", ReviewDispatchConsumer.as_asgi()),
    path("ws/portal/", PortalConsumer.as_asgi()),
    path("ws/console/", TeamConsoleConsumer.as_asgi()),
]
