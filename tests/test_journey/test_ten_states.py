"""The ten numbered states and their transition table (Backend v6.0 §3)."""

from __future__ import annotations

import pytest

from apps.journey.constants import JOURNEY_NUMBERS, STATE_KEYS
from apps.journey.models import (
    ALLOWED_TRANSITIONS,
    JourneyEvent,
    JourneyState,
    ceiling_for_state,
    journey_number,
    normalize_state,
)
from apps.journey.services.advance import InvalidTransition, advance
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def test_exactly_ten_numbered_states():
    assert len(JOURNEY_NUMBERS) == 10
    assert sorted(JOURNEY_NUMBERS.values()) == list(range(1, 11))


def test_dormant_is_off_ladder():
    """DORMANT is a real state with NO number — it is not step zero, it is beside the ladder."""
    assert "DORMANT" not in JOURNEY_NUMBERS
    assert journey_number("DORMANT") is None


def test_state_keys_are_in_ladder_order():
    assert STATE_KEYS[0] == "ARRIVED"
    assert STATE_KEYS[-1] == "CUSTOMER_SUCCESS"


@pytest.mark.parametrize(
    "stored,expected",
    [
        ("ENGAGED", "ASSESSMENT"),
        ("CLIENT", "NDA_REVIEW"),
        ("", "ARRIVED"),
        (None, "ARRIVED"),
        ("NOT_A_STATE", "ARRIVED"),
    ],
)
def test_normalize_collapses_to_least_privilege(stored, expected):
    """
    An unknown or stale value must never widen what a subject can see.

    Collapsing to ARRIVED (public ceiling) is the safe direction: the worst case is a
    subject briefly seeing less than they are entitled to, which a refresh corrects.
    """
    assert normalize_state(stored) == expected


def test_ceiling_rises_with_the_ladder_and_never_skips():
    ceilings = [ceiling_for_state(key) for key in STATE_KEYS]
    assert ceilings[0] == "public"
    assert ceilings[5] == "nda_only"          # state 6, NDA_REVIEW
    assert ceilings[-1] == "customer_contract"  # state 10


def test_full_happy_path_walks_one_to_ten():
    lead = LeadFactory(journey_state=JourneyState.ARRIVED.value, tier=1)
    walk = [
        (JourneyEvent.FIRST_TURN.value, "IN_REVIEW"),
        (JourneyEvent.LOOP_CLOSED.value, "DIAGNOSED"),
        (JourneyEvent.REVEAL_CLIENT_PAGE.value, "CLIENT_PAGE"),
        (JourneyEvent.GATE_INVITE.value, "INVITED"),
        (JourneyEvent.ACCEPT_INVITE.value, "NDA_REVIEW"),
        (JourneyEvent.FIRST_PAYMENT.value, "ASSESSMENT"),
        (JourneyEvent.POC_START.value, "POC"),
        (JourneyEvent.INTEGRATION_START.value, "INTEGRATION"),
        (JourneyEvent.CONTRACT_EXECUTED.value, "CUSTOMER_SUCCESS"),
    ]
    for event, expected in walk:
        result = advance(lead, event)
        assert result.to_state == expected, f"{event} should reach {expected}"
    lead.refresh_from_db()
    assert lead.journey_state == "CUSTOMER_SUCCESS"
    assert lead.journey_number == 10
    assert lead.state_key == "CUSTOMER_SUCCESS"


def test_nda_signed_does_not_move_the_state():
    """
    The NDA can be signed at any point inside NDA_REVIEW, so it raises the ceiling
    without advancing. It is still audited as a transition.
    """
    lead = LeadFactory(journey_state="NDA_REVIEW", tier=1)
    result = advance(lead, JourneyEvent.NDA_SIGNED.value)
    assert result.to_state == "NDA_REVIEW"
    assert result.changed is False
    assert result.transition is not None
    assert result.reveal["surface"] == "data_room"


def test_customer_success_is_terminal_on_the_ladder():
    """
    Expansion is a commercial motion INSIDE state 10, not a transition out of it. A
    journey event must never silently move a paying customer.
    """
    assert ALLOWED_TRANSITIONS[JourneyState.CUSTOMER_SUCCESS.value] == {}


def test_illegal_transition_raises_rather_than_mutating():
    lead = LeadFactory(journey_state=JourneyState.ARRIVED.value)
    with pytest.raises(InvalidTransition):
        advance(lead, JourneyEvent.CONTRACT_EXECUTED.value)
    lead.refresh_from_db()
    assert lead.journey_state == JourneyState.ARRIVED.value


def test_first_turn_is_idempotent():
    """
    Ingest calls this on every turn without tracking whether it is the first, so a
    repeat must be a satisfied no-op rather than an error.
    """
    lead = LeadFactory(journey_state=JourneyState.ARRIVED.value)
    advance(lead, JourneyEvent.FIRST_TURN.value)
    result = advance(lead, JourneyEvent.FIRST_TURN.value)
    assert result.changed is False
    assert result.to_state == "IN_REVIEW"


def test_deprecated_states_still_advance():
    """A row migration 0003 has not yet touched must still be able to move forward."""
    lead = LeadFactory(journey_state="ENGAGED", tier=1)
    result = advance(lead, JourneyEvent.POC_START.value)
    assert result.to_state == "POC"
