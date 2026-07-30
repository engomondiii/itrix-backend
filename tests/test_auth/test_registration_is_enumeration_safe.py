"""
REGISTRATION TELLS NOBODY ANYTHING (Architecture v2.9 R64, §27.6).

A registration form is exactly where somebody reaches for "That email is already
registered." That single field error publishes a customer list, and it is free to harvest:
anyone with a browser can type an address.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.clients.models import Client
from tests.factories.client_factory import ClientFactory

pytestmark = pytest.mark.django_db

ASSENT = [
    {"slug": "terms", "version": "1.2", "effective": "2026-07-30"},
    {"slug": "privacy", "version": "1.2", "effective": "2026-07-30"},
]


def _post(api_client, email):
    return api_client.post(
        reverse("clients:auth-register"),
        {
            "email": email,
            "password": "a-long-enough-password",
            "fullName": "A Person",
            "organization": "An Organisation",
            "assent": ASSENT,
        },
        format="json",
    )


def test_the_response_is_identical_for_a_free_and_a_held_address(api_client, settings):
    settings.ENABLE_OPEN_SIGNUP = True
    ClientFactory(email="held@example.com")

    free = _post(api_client, "free@example.com")
    held = _post(api_client, "held@example.com")

    assert free.status_code == held.status_code == 202
    # Byte-identical, not merely similar. A difference of one field is a difference an
    # attacker can read.
    assert free.content == held.content


def test_no_second_client_is_created_for_a_held_address(api_client, settings):
    settings.ENABLE_OPEN_SIGNUP = True
    ClientFactory(email="held@example.com", full_name="The Real Customer")
    _post(api_client, "HELD@example.com")
    assert Client.objects.filter(email__iexact="held@example.com").count() == 1
    assert Client.objects.get(email__iexact="held@example.com").full_name == "The Real Customer"


def test_the_holder_is_notified_and_the_requester_is_not(api_client, settings):
    """
    §27.6. The person who typed the address learns nothing; the person who OWNS it is told
    somebody tried, and how to secure the account.
    """
    settings.ENABLE_OPEN_SIGNUP = True
    holder = ClientFactory(email="held@example.com")
    _post(api_client, "held@example.com")

    from apps.emails.models import EmailLog

    notice = EmailLog.objects.filter(kind=EmailLog.Kind.ADDRESS_IN_USE).order_by("-created_at").first()
    assert notice is not None
    assert notice.to_email == holder.email
    # It carries no link that signs anyone in: a mail sent because a stranger typed an
    # address must not contain a credential.
    assert "token=" not in notice.body


def test_the_response_names_no_organisation_and_no_address(api_client, settings):
    settings.ENABLE_OPEN_SIGNUP = True
    ClientFactory(email="held@example.com", organization="Acme Corp")
    res = _post(api_client, "held@example.com")
    body = res.content.decode()
    assert "Acme" not in body
    assert "held@example.com" not in body
