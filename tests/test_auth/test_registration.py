"""
OPEN REGISTRATION (Architecture v2.9 §27, R60–R63).

The three assertions that matter are the ones about what registration does NOT do: it does
not advance the journey, it does not raise a ceiling, and it does not create a second
account for an address that already has one.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.clients.models import AccountOrigin, Client
from apps.journey.models import JourneyState
from apps.leads.models import Lead, LeadSource
from tests.factories.client_factory import ClientFactory

pytestmark = pytest.mark.django_db

ASSENT = [
    {"slug": "terms", "version": "1.2", "effective": "2026-07-30"},
    {"slug": "privacy", "version": "1.2", "effective": "2026-07-30"},
]


def _body(email="new.person@example.com", password="a-long-enough-password"):
    return {
        "email": email,
        "password": password,
        "fullName": "A Person",
        "organization": "An Organisation",
        "role": "Engineer",
        "assent": ASSENT,
    }


def test_registration_creates_a_lead_and_a_client(api_client, settings):
    settings.ENABLE_OPEN_SIGNUP = True
    res = api_client.post(reverse("clients:auth-register"), _body(), format="json")
    assert res.status_code == 202

    client = Client.objects.get(email="new.person@example.com")
    assert client.account_origin == AccountOrigin.SELF_SERVE
    assert client.credential.has_password
    assert client.lead.lead_source == LeadSource.SELF_SERVE
    assert client.lead.journey_state == JourneyState.ARRIVED


def test_registration_does_not_advance_the_journey(api_client, settings):
    """
    R61. `ACCEPT_INVITE` is legal only from `INVITED`, so calling it here would log a failed
    advance on every signup — and if that table were ever loosened, would put a silent
    account at State 6 with an `nda_only` ceiling.
    """
    settings.ENABLE_OPEN_SIGNUP = True
    api_client.post(reverse("clients:auth-register"), _body(), format="json")

    lead = Lead.objects.get(email="new.person@example.com")
    assert lead.journey_state == JourneyState.ARRIVED

    from apps.journey.models import JourneyTransition

    assert not JourneyTransition.objects.filter(lead=lead).exists()


def test_an_assent_record_exists_and_names_versions(api_client, settings):
    settings.ENABLE_OPEN_SIGNUP = True
    api_client.post(reverse("clients:auth-register"), _body(), format="json")

    from apps.legal.models import AssentRecord

    client = Client.objects.get(email="new.person@example.com")
    record = AssentRecord.objects.get(client=client)
    assert record.path == AssentRecord.Path.OPEN_REGISTRATION
    slugs = {entry["slug"] for entry in record.instruments}
    assert {"terms", "privacy"} <= slugs
    # Versions, not a boolean. A boolean stops being able to answer "what did they agree to"
    # the first time the Terms change.
    assert all(entry.get("version") for entry in record.instruments)


def test_registration_without_assent_is_refused(api_client, settings):
    """
    400 is safe to report: it names nothing about any address. It is our own programming
    error, not a fact about a customer.
    """
    settings.ENABLE_OPEN_SIGNUP = True
    body = _body()
    body.pop("assent")
    res = api_client.post(reverse("clients:auth-register"), body, format="json")
    assert res.status_code == 400
    assert not Client.objects.filter(email=body["email"]).exists()


def test_a_short_password_is_refused(api_client, settings):
    settings.ENABLE_OPEN_SIGNUP = True
    settings.PASSWORD_MIN_LENGTH = 12
    res = api_client.post(reverse("clients:auth-register"), _body(password="short"), format="json")
    assert res.status_code == 400


def test_register_404s_when_the_kill_switch_is_thrown(api_client, settings):
    """404, not 403. A disabled capability does not advertise itself (§27.10)."""
    settings.ENABLE_OPEN_SIGNUP = False
    res = api_client.post(reverse("clients:auth-register"), _body(), format="json")
    assert res.status_code == 404
    assert not Client.objects.filter(email="new.person@example.com").exists()


def test_one_active_client_per_email_is_a_database_constraint(settings):
    """
    R63. Enforced by the DB, not by a view check — which is what makes
    `authenticate_client()`'s `.first()` deterministic rather than a coin toss.
    """
    from django.db import IntegrityError, transaction

    ClientFactory(email="taken@example.com")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ClientFactory(email="TAKEN@example.com")


def test_an_inactive_account_does_not_burn_the_address(settings):
    """The constraint is conditioned on is_active: closing an account frees the address."""
    ClientFactory(email="left@example.com", is_active=False)
    ClientFactory(email="left@example.com")  # must not raise
    assert Client.objects.filter(email__iexact="left@example.com").count() == 2
