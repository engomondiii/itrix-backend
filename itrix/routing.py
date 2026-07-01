"""
Top-level WebSocket routing (Backend v4 §1.2, §Phase 2).

Assembles the WebSocket application: the ws_auth middleware stack wrapping the realtime
app's URLRouter. ``itrix/asgi.py`` mounts this under a ProtocolTypeRouter alongside the
HTTP (Django) application.

Kept import-light and side-effect-free so ``asgi.py`` can import it after Django setup.
"""

from __future__ import annotations

from channels.routing import URLRouter

from apps.realtime.middleware import WSAuthMiddlewareStack
from apps.realtime.routing import websocket_urlpatterns

websocket_application = WSAuthMiddlewareStack(URLRouter(websocket_urlpatterns))
