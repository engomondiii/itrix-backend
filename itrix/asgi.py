"""
ASGI config for the itriX project (v4.0 Phase 2).

Mounts a ProtocolTypeRouter so a single ASGI server handles both planes:

    http       → the Django application (all REST endpoints, unchanged)
    websocket  → the itriX WebSocket application (ws_auth stack + realtime URLRouter)

The WebSocket application is imported lazily AFTER ``get_asgi_application()`` runs
``django.setup()``, so app models are ready when the consumers import them. If Channels
is unavailable for any reason, we fall back to HTTP-only so a misconfigured realtime
layer never takes the REST API down.
"""

from __future__ import annotations

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "itrix.settings.production")

# Initialise Django (runs django.setup()) before importing anything that touches models.
django_asgi_app = get_asgi_application()

try:
    from channels.routing import ProtocolTypeRouter

    from itrix.routing import websocket_application

    application = ProtocolTypeRouter(
        {
            "http": django_asgi_app,
            "websocket": websocket_application,
        }
    )
except Exception:  # noqa: BLE001 - never let a realtime misconfig break HTTP
    application = django_asgi_app
