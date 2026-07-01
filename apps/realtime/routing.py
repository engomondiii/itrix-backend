"""
Realtime WebSocket URL routes.

    ws/review/{session}/   ReviewConsumer      (PUBLIC / capability token)
    ws/portal/             PortalConsumer      (CLIENT plane, client-JWT)
    ws/console/            TeamConsoleConsumer  (TEAM plane, team-JWT)

Mounted by the top-level itrix/routing.py behind the ws_auth middleware stack.
"""

from __future__ import annotations

from django.urls import path

from apps.realtime.consumers.portal import PortalConsumer
from apps.realtime.consumers.review import ReviewConsumer
from apps.realtime.consumers.team_console import TeamConsoleConsumer

websocket_urlpatterns = [
    path("ws/review/<str:session>/", ReviewConsumer.as_asgi()),
    path("ws/portal/", PortalConsumer.as_asgi()),
    path("ws/console/", TeamConsoleConsumer.as_asgi()),
]
