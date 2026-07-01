"""ws_auth middleware: resolves client-JWT / capability token, rejects garbage."""

from __future__ import annotations

import pytest

from apps.realtime.middleware import WSAuthMiddleware
from tests.factories.client_factory import ClientFactory
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def _mw():
    return WSAuthMiddleware(inner=None)


def test_client_token_resolves_to_client():
    from apps.clients.tokens import build_tokens_for_client

    client = ClientFactory()
    token = build_tokens_for_client(client)["access"]
    resolved = _mw()._try_client_token(token)
    assert resolved is not None
    assert resolved.id == client.id


def test_garbage_token_resolves_to_nothing():
    mw = _mw()
    assert mw._try_client_token("garbage") is None
    assert mw._try_team_token("garbage") is None
    assert mw._try_capability_token("garbage") is None


def test_capability_token_resolves():
    from apps.journey.services import capability_token as ct

    lead = LeadFactory()
    token = ct.mint(sub=str(lead.id), typ=ct.TOKEN_CLIENT_PAGE, state="CLIENT_PAGE")
    payload = _mw()._try_capability_token(token)
    assert payload is not None
    assert payload.sub == str(lead.id)


def test_team_token_resolves_to_user():
    from apps.authentication.tokens import build_tokens_for_user
    from tests.factories.user_factory import AdminUserFactory

    user = AdminUserFactory()
    token = build_tokens_for_user(user)["access"]
    resolved = _mw()._try_team_token(token)
    assert resolved is not None
    assert resolved.id == user.id


def test_client_token_is_not_a_team_token():
    # Cross-plane: a client token must NOT resolve as a team user.
    from apps.clients.tokens import build_tokens_for_client

    client = ClientFactory()
    ctoken = build_tokens_for_client(client)["access"]
    assert _mw()._try_team_token(ctoken) is None
