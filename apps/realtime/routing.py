"""
Realtime WebSocket URL routes.

    ws/review/{session}/       ReviewConsumer       (PUBLIC / capability token)
    ws/client-page/{token}/    ClientPageConsumer   (PUBLIC / client_page token)
    ws/portal/                 PortalConsumer       (CLIENT plane, client-JWT)
    ws/console/                TeamConsoleConsumer   (TEAM plane, team-JWT)

Mounted by the top-level itrix/routing.py behind the ws_auth middleware stack.

v4.0.3: the client page opens ``ws/client-page/{token}/`` (the frontend's wsUrls.clientPage).
Before this route existed the handshake 404'd, which is why the client-page chat and the
live content stream failed. ClientPageConsumer streams both the page generation and the
chat replies token-by-token.
"""

from __future__ import annotations

from django.urls import path

from apps.realtime.consumers.portal import PortalConsumer
from apps.realtime.consumers.review import ClientPageConsumer, ReviewConsumer
from apps.realtime.consumers.team_console import TeamConsoleConsumer

websocket_urlpatterns = [
    path("ws/review/<str:session>/", ReviewConsumer.as_asgi()),
    path("ws/client-page/<str:token>/", ClientPageConsumer.as_asgi()),
    path("ws/portal/", PortalConsumer.as_asgi()),
    path("ws/console/", TeamConsoleConsumer.as_asgi()),
]
