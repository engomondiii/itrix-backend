"""
The commitment gate is applied AT THE PAYLOAD (Backend v6.0 §Phase 3, Architecture §5).

    A commitment card present in a payload where ``value_delivered`` is false is A DEFECT.

The gate is enforced when the card is BUILT — not by the frontend declining to render it.
A frontend-side gate means the card was on the wire, and anything on the wire can be
read: by a proxy, by a devtools panel, by a screenshot, by the next refactor.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.journey.services import cards
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def _kinds(payloads):
    return {c["kind"] for c in payloads}


def test_no_commitment_card_before_value_is_delivered():
    """THE DEFECT CHECK."""
    lead = LeadFactory(journey_state="CLIENT_PAGE", value_delivered_at=None)
    payloads = cards.build(lead)
    assert not (_kinds(payloads) & cards.COMMITMENT_CARDS)


def test_commitment_cards_appear_once_value_is_delivered():
    lead = LeadFactory(journey_state="CLIENT_PAGE", tier=1,
                       value_delivered_at=timezone.now())
    assert _kinds(cards.build(lead)) & cards.COMMITMENT_CARDS


def test_the_specialist_card_is_gated():
    lead = LeadFactory(journey_state="CLIENT_PAGE", value_delivered_at=None)
    assert cards.build_specialist_card(lead) is None


def test_the_scheduling_card_is_gated():
    lead = LeadFactory(journey_state="CLIENT_PAGE", value_delivered_at=None)
    assert cards.build_scheduling_card(lead) is None


def test_the_gate_fails_closed_on_error():
    """A gate that fails open is not a gate."""
    assert cards._commitment_permitted(None, cards.CARD_SCHEDULING) is False


def test_an_unknown_card_kind_is_a_server_error():
    """
    Same reasoning as an unknown sidebar section: a generic renderer would display a
    payload nobody designed a disclosure review for.
    """
    with pytest.raises(cards.UnknownCardKind):
        cards.Card(kind="not_a_real_card", title="x")


def test_the_relationship_team_card_is_never_gated():
    """
    R30 is an ABSOLUTE: a customer can always reach a named human WITHOUT first
    negotiating with an agent. Gating this card would be the negotiation.
    """
    from apps.customer_success.models import RelationshipTeamMember
    from tests.factories.client_factory import ClientFactory

    lead = LeadFactory(value_delivered_at=None)
    client = ClientFactory(lead=lead)
    RelationshipTeamMember.objects.create(
        client=client, display_name="A Person", role="customer_success",
        helps_with="Day-to-day",
    )
    card = cards.build_relationship_team_card(client)
    assert card is not None
    assert card.dismissible is False


def test_the_support_card_is_never_gated():
    from apps.customer_success.models import SupportRequest
    from tests.factories.client_factory import ClientFactory

    lead = LeadFactory(value_delivered_at=None)
    client = ClientFactory(lead=lead)
    SupportRequest.objects.create(client=client, subject="Broken", body="It is broken")
    assert cards.build_support_card(client) is not None


def test_the_disclosure_boundary_card_names_the_next_step_not_the_withholding():
    """
    §13.2: name WHAT WOULD BECOME AVAILABLE and WHAT IT WOULD REQUIRE — never what is
    being withheld. "We are not showing you X" tells the visitor that X exists.
    """
    lead = LeadFactory(journey_state="CLIENT_PAGE", value_delivered_at=timezone.now())
    card = cards.build_disclosure_boundary_card(lead)
    assert card is not None
    body = (card.title + " " + card.body).lower()
    for leak in ("cannot show", "not showing", "withheld", "restricted", "denied", "hidden"):
        assert leak not in body


def test_the_boundary_card_is_absent_before_value():
    """Before value, a boundary card is a commitment ask wearing a disguise."""
    lead = LeadFactory(journey_state="CLIENT_PAGE", value_delivered_at=None)
    assert cards.build_disclosure_boundary_card(lead) is None


def test_the_nba_card_passes_through_the_precedence_rule(settings):
    settings.ENABLE_CUSTOMER_FIRST_NBA = True
    from apps.governance.services import nba_precedence as nba

    lead = LeadFactory(journey_state="ASSESSMENT", value_delivered_at=timezone.now())
    decision = nba.rank(
        [nba.ActionCandidate(key="expand", label="Expand", kind=nba.KIND_COMMERCIAL,
                             commercial=True, weight=100),
         nba.ActionCandidate(key="support", label="Resolve", kind=nba.KIND_SUPPORT,
                             weight=1)],
        signals={"blocking_support": True, "outcome_off_plan": False,
                 "adoption_below_plan": False, "negative_trust": False,
                 "health": "stable", "expansion_allowed": True},
    )
    card = cards.build_nba_card(lead, decision=decision)
    assert card is not None
    assert card.title == "Resolve"


def test_every_card_kind_is_in_the_closed_vocabulary():
    lead = LeadFactory(journey_state="CLIENT_PAGE", tier=1,
                       value_delivered_at=timezone.now())
    for payload in cards.build(lead):
        assert payload["kind"] in cards.CARD_KINDS
