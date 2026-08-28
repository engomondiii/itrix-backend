"""
The NDA request from the Documents screen (2026-08-10).

The control used to be a link into Messages: pressing it navigated the customer
out of the room they were trying to open. It now submits in place, and this
suite pins what the confirmation promises — the stamp, the inbox note, and that
a request is never mistaken for a signature.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.clients.tokens import build_tokens_for_client
from apps.conversations.models import SenderKind
from apps.conversations.services.history import get_or_create_portal_conversation
from tests.factories.client_factory import ClientFactory

pytestmark = pytest.mark.django_db

URL = "/api/v1/portal/nda/request/"


def _authed(row) -> APIClient:
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {build_tokens_for_client(row)['access']}")
    return api


def test_requesting_an_nda_stamps_the_client_and_returns_the_confirmation():
    row = ClientFactory(nda_signed=False)
    res = _authed(row).post(URL, {}, format="json")

    assert res.status_code == 202
    assert res.json()["ndaRequested"] is True
    assert "inbox" in res.json()["message"].lower()

    row.refresh_from_db()
    assert row.nda_requested_at is not None
    # A request is NOT a signature or content authorization.
    assert row.nda_signed is False
    message = res.json()["message"].lower()
    assert "restricted material" in message
    assert "authorized" in message


def test_the_request_lands_in_the_workspace_inbox():
    row = ClientFactory(nda_signed=False)
    _authed(row).post(URL, {}, format="json")

    conv = get_or_create_portal_conversation(row)
    bodies = [m.body for m in conv.messages.filter(sender_kind=SenderKind.AGENT)]
    assert any("NDA" in b for b in bodies), bodies


def test_asking_twice_keeps_the_first_timestamp_and_does_not_repeat_the_note():
    row = ClientFactory(nda_signed=False)
    api = _authed(row)
    api.post(URL, {}, format="json")
    row.refresh_from_db()
    first = row.nda_requested_at

    assert api.post(URL, {}, format="json").status_code == 202
    row.refresh_from_db()
    assert row.nda_requested_at == first

    conv = get_or_create_portal_conversation(row)
    notes = [m for m in conv.messages.filter(sender_kind=SenderKind.AGENT) if "NDA" in m.body]
    assert len(notes) == 1


def test_a_signed_client_is_told_the_agreement_is_already_in_place_without_promising_access():
    row = ClientFactory(nda_signed=True)
    res = _authed(row).post(URL, {}, format="json")
    assert res.status_code == 200
    assert "already" in res.json()["detail"].lower()
    assert "data room" not in res.json()["detail"].lower()


def test_the_endpoint_requires_a_client():
    assert APIClient().post(URL, {}, format="json").status_code in (401, 403)
