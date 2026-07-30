"""
NOBODY IS ASKED TO CREATE WHAT THEY HAVE (Architecture v2.9 R67, §27.8).

A person who registered on arrival, conversed, and reached State 5 must not be served a card
offering the workspace they are already sitting inside. That is not cosmetic: it is the
platform announcing it does not know who it is talking to, on the screen where it has just
claimed to have read them closely.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.journey.services.gate import account_invite_allowed, commitment_allowed
from tests.factories.client_factory import ClientFactory
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def _qualified_lead():
    return LeadFactory(tier=1, journey_state="INVITED", value_delivered_at=timezone.now())


def test_a_lead_without_an_account_is_still_asked():
    lead = _qualified_lead()
    assert account_invite_allowed(lead) is True
    assert commitment_allowed(lead, "account_creation") is True


def test_a_lead_with_an_account_is_not_asked_again():
    lead = _qualified_lead()
    ClientFactory(lead=lead)
    # The invite GATE is unchanged — this subject did qualify. What changes is that we no
    # longer ASK, because the thing being asked for already exists.
    assert account_invite_allowed(lead) is True
    assert commitment_allowed(lead, "account_creation") is False


def test_the_suppression_is_specific_to_account_creation():
    """Every other commitment ask is untouched: having a workspace does not stop us asking
    about an NDA or an evaluation."""
    lead = _qualified_lead()
    ClientFactory(lead=lead)
    assert commitment_allowed(lead, "nda") is True
    assert commitment_allowed(lead, "paid_evaluation") is True
