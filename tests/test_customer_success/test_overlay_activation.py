"""
R16 — customer-success modules activate at the FIRST PAYMENT, not at license-out
(Architecture §7.1, Backend v6.0 §Phase 2).

    A paid Assessment customer ALREADY has named owners, support access and success goals.

The rule exists because a customer who has just paid is exposed: they have committed
money and have nobody to call. Waiting for license-out makes the riskiest period of the
relationship the one with the least support.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.customer_success.models import RelationshipTeamMember
from apps.customer_success.services import overlay
from tests.factories.client_factory import ClientFactory
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def test_activation_records_the_first_payment():
    client = ClientFactory(lead=LeadFactory())
    assert client.first_payment_recorded_at is None
    overlay.activate(client)
    client.refresh_from_db()
    assert client.first_payment_recorded_at is not None


def test_activation_seeds_all_four_named_roles():
    """
    R30 is an absolute: a customer can always reach a NAMED human. Four roles, always.
    """
    client = ClientFactory(lead=LeadFactory())
    overlay.activate(client)
    roles = set(
        RelationshipTeamMember.objects.filter(client=client).values_list("role", flat=True)
    )
    assert roles == {"customer_success", "technical", "executive", "support"}


def test_no_role_is_left_nameless():
    """
    A customer told they have a named owner who then sees "TBD" has been told something
    untrue. The placeholder names the TEAM, which is honest.
    """
    client = ClientFactory(lead=LeadFactory())
    overlay.activate(client)
    for member in RelationshipTeamMember.objects.filter(client=client):
        assert member.display_name.strip()
        assert "TBD" not in member.display_name
        assert member.helps_with.strip()


def test_activation_is_idempotent():
    """advance() may retry; a retried transition must not duplicate the team."""
    client = ClientFactory(lead=LeadFactory())
    overlay.activate(client)
    first_stamp = client.first_payment_recorded_at
    overlay.activate(client)
    client.refresh_from_db()
    assert RelationshipTeamMember.objects.filter(client=client).count() == 4
    assert client.first_payment_recorded_at == first_stamp


def test_the_overlay_is_active_from_state_seven_not_ten(paying_client):
    """THE POINT OF R16. Assessment (7), not customer success (10)."""
    assert overlay.is_active(paying_client) is True


def test_a_first_payment_transition_activates_the_overlay():
    """The journey hook: FIRST_PAYMENT -> overlay.activate()."""
    from apps.journey.services.advance import advance

    lead = LeadFactory(journey_state="NDA_REVIEW", tier=1)
    client = ClientFactory(lead=lead)
    advance(lead, "first_payment")
    client.refresh_from_db()
    assert client.first_payment_recorded_at is not None
    assert RelationshipTeamMember.objects.filter(client=client).count() == 4


def test_a_contracted_customer_has_the_overlay_even_without_a_payment_stamp():
    """A data gap must not withdraw support access from someone who is paying."""
    client = ClientFactory(lead=LeadFactory())
    client.contract_state = "executed"
    client.save(update_fields=["contract_state"])
    assert overlay.is_active(client) is True
