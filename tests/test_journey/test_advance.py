"""Journey state machine: valid transitions, guards, value stamping, reveals."""

from __future__ import annotations

import pytest

from apps.journey.models import JourneyEvent, JourneyState
from apps.journey.services.advance import (
    InvalidTransition,
    advance,
    mark_diagnosed,
    reveal_client_page,
)
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def test_qualify_advances_to_diagnosed_and_stamps_value():
    lead = LeadFactory(journey_state="IN_REVIEW", value_delivered_at=None)
    result = mark_diagnosed(lead)
    lead.refresh_from_db()
    assert lead.journey_state == JourneyState.DIAGNOSED
    assert lead.value_delivered_at is not None
    assert result.changed is True


def test_reveal_client_page_mints_token():
    lead = LeadFactory(journey_state="DIAGNOSED")
    result = reveal_client_page(lead)
    lead.refresh_from_db()
    assert lead.journey_state == JourneyState.CLIENT_PAGE
    assert result.reveal["surface"] == "client_page"
    assert result.reveal["capability_token"]


def test_invalid_transition_raises():
    lead = LeadFactory(journey_state="ARRIVED")
    with pytest.raises(InvalidTransition):
        advance(lead, JourneyEvent.ENGAGE)


def test_transition_is_recorded():
    lead = LeadFactory(journey_state="IN_REVIEW")
    mark_diagnosed(lead)
    assert lead.journey_transitions.filter(to_state=JourneyState.DIAGNOSED).exists()


def test_idempotent_reapply_is_noop():
    lead = LeadFactory(journey_state="IN_REVIEW")
    mark_diagnosed(lead)  # → DIAGNOSED
    # Re-applying the same qualify event when already DIAGNOSED is a satisfied no-op.
    result = advance(lead, JourneyEvent.QUALIFY)
    assert result.changed is False
    assert lead.journey_state == JourneyState.DIAGNOSED


def test_full_happy_path_to_engaged():
    """
    UPDATED FOR v6.0. The v4.0 ladder ended CLIENT -> ENGAGED. v6.0 renames CLIENT to
    NDA_REVIEW (state 6) and splits ENGAGED into ASSESSMENT / POC / INTEGRATION, so this
    path now ends at ASSESSMENT (state 7).

    ``ENGAGE`` is retained as a backward-compatible alias for ``FIRST_PAYMENT`` so a
    caller that has not yet migrated still lands somewhere coherent — that alias is
    exactly what this test now pins.
    """
    lead = LeadFactory(journey_state="IN_REVIEW", tier=1)
    mark_diagnosed(lead)
    reveal_client_page(lead)
    advance(lead, JourneyEvent.GATE_INVITE)
    assert lead.journey_state == JourneyState.INVITED
    advance(lead, JourneyEvent.ACCEPT_INVITE)
    assert lead.journey_state == JourneyState.NDA_REVIEW
    advance(lead, JourneyEvent.ENGAGE)
    assert lead.journey_state == JourneyState.ASSESSMENT
    assert lead.journey_number == 7
