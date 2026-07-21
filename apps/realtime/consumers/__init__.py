"""
Realtime consumers.

    ReviewDispatchConsumer  ws/review/{segment}/     resolves thread-vs-session
    ThreadConsumer          (via dispatch)           v6.0 anonymous thread plane
    ReviewConsumer          (via dispatch)           v4.0 review session plane
    ClientPageConsumer      ws/client-page/{token}/  client page live generation
    PortalConsumer          ws/portal/               client plane
    TeamConsoleConsumer     ws/console/              team plane

Imports are lazy inside ``routing.py`` rather than eager here, so a consumer that fails
to import cannot take down the whole WebSocket application at startup.
"""

from __future__ import annotations

__all__ = [
    "ReviewDispatchConsumer",
    "ThreadConsumer",
    "ReviewConsumer",
    "ClientPageConsumer",
    "PortalConsumer",
    "TeamConsoleConsumer",
]
