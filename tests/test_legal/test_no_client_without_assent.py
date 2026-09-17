"""No active Client exists without the assent that created it."""

from __future__ import annotations

import pytest

from apps.clients.models import Client
from apps.clients.services.invite import mint_invite
from apps.clients.services.invite_versioned import claim_invite_with_version_integrity
from apps.clients.services.registration import register_client
from apps.legal.models import AssentRecord
from apps.legal.services import assent as assent_svc
from apps.legal.services import instruments as instruments_svc
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def current_assent():
    return instruments_svc.current_versions(["terms", "privacy"])


def test_the_invite_claim_path_records_assent():
    lead = LeadFactory(tier=1, journey_state="INVITED")
    token = mint_invite(lead)
    client, _ = claim_invite_with_version_integrity(
        token,
        email="invited@example.com",
        password="a-long-enough-password",
        assent_versions=current_assent(),
    )
    assert AssentRecord.objects.filter(client=client).exists()


def test_the_registration_path_records_assent():
    outcome = register_client(
        email="selfserve@example.com",
        password="a-long-enough-password",
        full_name="A Person",
        organization="An Organisation",
        assent_versions=current_assent(),
    )
    assert AssentRecord.objects.filter(client=outcome.client).exists()


def test_no_active_client_anywhere_lacks_an_assent_record():
    register_client(
        email="another@example.com",
        password="a-long-enough-password",
        full_name="A Person",
        organization="An Organisation",
        assent_versions=current_assent(),
    )
    assert not assent_svc.clients_without_assent().exists()


def test_an_assent_failure_takes_the_client_with_it(monkeypatch):
    def _refuse(**kwargs):
        raise assent_svc.AssentRefused("no")

    monkeypatch.setattr(assent_svc, "record_in_transaction", _refuse)

    with pytest.raises(assent_svc.AssentRefused):
        register_client(
            email="doomed@example.com",
            password="a-long-enough-password",
            full_name="A Person",
            organization="An Organisation",
            assent_versions=current_assent(),
        )

    assert not Client.objects.filter(email="doomed@example.com").exists()
