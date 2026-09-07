from __future__ import annotations

import pytest
from django.test import override_settings

from apps.clients.models import Client
from apps.clients.services.invite import mint_invite
from apps.clients.services.invite_versioned import (
    InviteLegalTermsChanged,
    claim_invite_with_version_integrity,
)
from apps.clients.services.registration import (
    RegistrationLegalTermsChanged,
    register_client,
)
from apps.legal.models import AssentRecord
from apps.legal.services import instruments as instruments_svc
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db

V1 = {
    "LEGAL_PUBLISHED": True,
    "LEGAL_TERMS_VERSION": "race-1",
    "LEGAL_TERMS_EFFECTIVE": "2026-09-01",
    "LEGAL_PRIVACY_VERSION": "race-1",
    "LEGAL_PRIVACY_EFFECTIVE": "2026-09-01",
}
V2 = {
    "LEGAL_PUBLISHED": True,
    "LEGAL_TERMS_VERSION": "race-2",
    "LEGAL_TERMS_EFFECTIVE": "2026-09-07",
    "LEGAL_PRIVACY_VERSION": "race-2",
    "LEGAL_PRIVACY_EFFECTIVE": "2026-09-07",
}


def rendered():
    return instruments_svc.current_versions(["terms", "privacy"])


def test_open_signup_stale_rendered_versions_roll_back_then_current_versions_succeed():
    with override_settings(**V1):
        shown_v1 = rendered()

    with override_settings(**V2):
        with pytest.raises(RegistrationLegalTermsChanged):
            register_client(
                email="race-open@example.com",
                password="a-long-enough-password",
                full_name="Race Open",
                organization="Example",
                assent_versions=shown_v1,
            )

        assert not Client.objects.filter(email="race-open@example.com").exists()
        assert not AssentRecord.objects.filter(client_email_at_assent="race-open@example.com").exists()

        shown_v2 = rendered()
        outcome = register_client(
            email="race-open@example.com",
            password="a-long-enough-password",
            full_name="Race Open",
            organization="Example",
            assent_versions=shown_v2,
        )
        record = AssentRecord.objects.get(client=outcome.client)
        assert record.version_of("terms") == "race-2"
        assert record.version_of("privacy") == "race-2"


def test_invite_stale_rendered_versions_do_not_consume_claim_then_current_versions_succeed():
    lead = LeadFactory(tier=1, journey_state="INVITED")
    token = mint_invite(lead)

    with override_settings(**V1):
        shown_v1 = rendered()

    with override_settings(**V2):
        with pytest.raises(InviteLegalTermsChanged):
            claim_invite_with_version_integrity(
                token,
                email="race-invite@example.com",
                password="a-long-enough-password",
                assent_versions=shown_v1,
            )

        assert not Client.objects.filter(lead=lead).exists()
        assert not AssentRecord.objects.filter(client_email_at_assent="race-invite@example.com").exists()

        shown_v2 = rendered()
        client, _ = claim_invite_with_version_integrity(
            token,
            email="race-invite@example.com",
            password="a-long-enough-password",
            assent_versions=shown_v2,
        )
        record = AssentRecord.objects.get(client=client)
        assert record.version_of("terms") == "race-2"
        assert record.version_of("privacy") == "race-2"
