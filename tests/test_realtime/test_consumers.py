"""
Consumer tests using Channels' in-memory layer.

These verify the connect/authorize handshake for each plane:
  * review socket accepts an anonymous connection scoped to a session,
  * portal socket refuses a connection without a client identity,
  * portal socket accepts when the scope carries a client (as ws_auth would set).

We drive the consumers with WebsocketCommunicator and a hand-built scope, so no real
Redis/broker is needed (InMemoryChannelLayer is configured when ENABLE_REALTIME is off).
"""

from __future__ import annotations

import pytest
from channels.testing import WebsocketCommunicator

from apps.realtime.consumers.portal import PortalConsumer
from apps.realtime.consumers.review import ReviewConsumer
from tests.factories.client_factory import ClientFactory
from tests.factories.lead_factory import LeadFactory

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


async def _make(consumer_cls, path, scope_extra):
    communicator = WebsocketCommunicator(consumer_cls.as_asgi(), path)
    communicator.scope.update(scope_extra)
    return communicator


@pytest.mark.asyncio
async def test_review_consumer_accepts_with_session():
    from channels.db import database_sync_to_async

    # The review consumer keys the thread by the URL session string; no lead FK needed.
    await database_sync_to_async(LeadFactory)()
    communicator = await _make(
        ReviewConsumer,
        "/ws/review/sess-ws/",
        {
            "url_route": {"kwargs": {"session": "sess-ws"}},
            "plane": "public",
            "cap_payload": None,
            "client": None,
            "team_user": None,
            "ws_subprotocol_ack": None,
        },
    )
    connected, _ = await communicator.connect()
    assert connected is True
    await communicator.disconnect()


@pytest.mark.asyncio
async def test_portal_consumer_refuses_without_client():
    communicator = await _make(
        PortalConsumer,
        "/ws/portal/",
        {"plane": "public", "client": None, "ws_subprotocol_ack": None},
    )
    connected, _ = await communicator.connect()
    assert connected is False
    await communicator.disconnect()


@pytest.mark.asyncio
async def test_portal_consumer_accepts_with_client():
    from channels.db import database_sync_to_async

    client = await database_sync_to_async(ClientFactory)()
    communicator = await _make(
        PortalConsumer,
        "/ws/portal/",
        {"plane": "client", "client": client, "ws_subprotocol_ack": None},
    )
    connected, _ = await communicator.connect()
    assert connected is True
    await communicator.disconnect()
