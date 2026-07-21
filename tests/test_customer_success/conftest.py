"""Shared customer-success fixtures."""

from __future__ import annotations

import pytest
from django.utils import timezone


@pytest.fixture(autouse=True)
def _enable(settings):
    settings.ENABLE_CUSTOMER_SUCCESS = True
    settings.CUSTOMER_CONTRACT_TIER_ENABLED = True


@pytest.fixture
def paying_client(db):
    """A client who has paid — the overlay is active (R16)."""
    from tests.factories.client_factory import ClientFactory
    from tests.factories.lead_factory import LeadFactory

    lead = LeadFactory(journey_state="ASSESSMENT")
    client = ClientFactory(lead=lead, nda_signed=True)
    client.first_payment_recorded_at = timezone.now()
    client.save(update_fields=["first_payment_recorded_at"])
    return client
