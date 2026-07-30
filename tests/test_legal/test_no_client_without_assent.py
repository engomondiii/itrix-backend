"""
NO CLIENT EXISTS WITHOUT THE ASSENT THAT CREATED IT (Architecture v2.9 R62, §19.10).

── ASSERTED ACROSS EVERY DOOR, ONCE, RATHER THAN TRUSTED VIEW BY VIEW ──────
There are three ways to create a Client: the emailed capability link, an invitation code
from a cold start, and self-serve registration. A per-view habit would not catch a FOURTH
door added later. This does: a new path that skips the recorder fails this file.
"""

from __future__ import annotations

import pytest

from apps.clients.models import Client
from apps.clients.services.invite import claim_invite, mint_invite
from apps.clients.services.registration import register_client
from apps.legal.models import AssentRecord
from apps.legal.services import assent as assent_svc
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db

ASSENT = [
    {"slug": "terms", "version": "1.2", "effective": "2026-07-30"},
    {"slug": "privacy", "version": "1.2", "effective": "2026-07-30"},
]


def test_the_invite_claim_path_records_assent():
    lead = LeadFactory(tier=1, journey_state="INVITED")
    token = mint_invite(lead)
    client, _ = claim_invite(
        token,
        email="invited@example.com",
        password="a-long-enough-password",
        assent_versions=ASSENT,
    )
    assert AssentRecord.objects.filter(client=client).exists()


def test_the_registration_path_records_assent():
    outcome = register_client(
        email="selfserve@example.com",
        password="a-long-enough-password",
        full_name="A Person",
        organization="An Organisation",
        assent_versions=ASSENT,
    )
    assert AssentRecord.objects.filter(client=outcome.client).exists()


def test_no_active_client_anywhere_lacks_an_assent_record():
    """
    The invariant as a QUERY, not only as a per-path assertion. Exposed so it can be checked
    against production data too — a non-empty result there is a governance defect rather than
    a backlog item.
    """
    LeadFactory(tier=1, journey_state="INVITED")
    register_client(
        email="another@example.com",
        password="a-long-enough-password",
        full_name="A Person",
        organization="An Organisation",
        assent_versions=ASSENT,
    )
    assert not assent_svc.clients_without_assent().exists()


def test_an_assent_failure_takes_the_client_with_it(monkeypatch):
    """
    The whole reason the record is written INSIDE the creating transaction. A view that
    recorded it just afterwards and crashed in between would leave an account whose basis
    nobody can produce — and that cannot be repaired later by guessing what they read.
    """

    def _refuse(**kwargs):
        raise assent_svc.AssentRefused("no")

    monkeypatch.setattr(assent_svc, "record_in_transaction", _refuse)

    with pytest.raises(assent_svc.AssentRefused):
        register_client(
            email="doomed@example.com",
            password="a-long-enough-password",
            full_name="A Person",
            organization="An Organisation",
            assent_versions=ASSENT,
        )

    assert not Client.objects.filter(email="doomed@example.com").exists()
