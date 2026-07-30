"""
The customer health board — the renames and the four classes (Backend v7.1 §Phase 1).

── WHY THE RENAMES ARE NOT COSMETIC ────────────────────────────────────────
    board -> results         ``board`` named the WIDGET. A key named after its own UI
                             cannot be reused by a second view without lying.
    organization -> company  One name for one thing across every row-level resource.
    health -> healthClass    ``health`` reads like a score. It is a CLASS from a closed
                             set of four, and naming it as one stops a chart treating it
                             as ordinal.

── AND critical IS NEVER COLLAPSED ─────────────────────────────────────────
It is the difference between "watch this" and "someone should call them today". An
operator who cannot see it will treat the whole board as advisory, which is exactly how
the customer-first rule stops being load-bearing.
"""

from __future__ import annotations

import pytest

from tests.factories.client_factory import ClientFactory

pytestmark = pytest.mark.django_db


def _team_client(role: str = "ASSESSMENT"):
    from django.contrib.auth import get_user_model
    from rest_framework.test import APIClient

    User = get_user_model()
    user = User.objects.create_user(
        email=f"{role.lower()}-cust@itrix.test",
        password="a-long-enough-password",
        role=role,
        is_active=True,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_the_payload_key_is_results_not_board():
    body = _team_client().get("/api/v1/cockpit/customers/").json()
    assert "results" in body
    assert "board" not in body


def test_health_classes_are_named_in_the_payload():
    """
    So a chart cannot invent a fifth class or collapse ``critical`` into ``at_risk`` on its
    own.
    """
    body = _team_client().get("/api/v1/cockpit/customers/").json()
    assert body["healthClasses"] == ["stable", "at_risk", "critical", "unknown"]


def test_the_four_classes_include_critical():
    from apps.cockpit.services.customers import HEALTH_CLASSES

    assert "critical" in HEALTH_CLASSES
    assert len(HEALTH_CLASSES) == 4


def test_rows_use_company_and_healthClass_and_keep_reasons():
    # ``Client.lead`` is NOT NULL, so the factory is the only correct way to build one.
    ClientFactory(organization="Example Corp", is_active=True)
    rows = _team_client().get("/api/v1/cockpit/customers/").json()["results"]
    assert rows, "an active client should produce a row"
    row = rows[0]

    assert "company" in row and "organization" not in row
    assert "healthClass" in row and "health" not in row
    # A class an operator cannot explain is a class they learn to ignore.
    assert "reasons" in row
    # The customer-first rule, as data.
    assert "expansionAllowed" in row


def test_an_unrecognised_class_resolves_to_unknown_not_passed_through():
    """
    The dashboard sorts and colours on this value. A stray string would sort last and read
    as healthy, which is the worst possible default for a health board.
    """
    from unittest.mock import patch

    ClientFactory(organization="Odd Corp", is_active=True)

    class FakeAssessment:
        health = "totally_fine_actually"
        reasons: list = []
        blocking_support = False
        outcomes_off_plan = 0
        negative_pulse = False
        degraded_deployments = 0
        permits_expansion = True

    with patch(
        "apps.customer_success.services.health_calculator.calculate",
        return_value=FakeAssessment(),
    ):
        from apps.cockpit.services import customers

        rows = customers.results()

    assert rows[0]["healthClass"] == "unknown"


def test_worst_first_ordering_is_part_of_the_contract():
    """The board exists to surface who needs attention, so the order is not presentation."""
    from unittest.mock import patch

    for name in ("Stable Co", "Critical Co", "Risky Co"):
        ClientFactory(organization=name, is_active=True)

    healths = iter(["stable", "critical", "at_risk"])

    def fake_calculate(client):
        class A:
            health = next(healths)
            reasons: list = []
            blocking_support = False
            outcomes_off_plan = 0
            negative_pulse = False
            degraded_deployments = 0
            permits_expansion = True
        return A()

    with patch(
        "apps.customer_success.services.health_calculator.calculate",
        side_effect=fake_calculate,
    ):
        from apps.cockpit.services import customers

        rows = customers.results()

    assert [r["healthClass"] for r in rows][:3] == ["critical", "at_risk", "stable"]


def test_the_customer_read_carries_no_commercial_signal():
    """
    No licence-out probability, no lead score, no tier. A customer-success read that carried
    them would invite an operator to open a health review and leave with an expansion plan
    — the precise inversion the customer-first rule exists to prevent.
    """
    client_row = ClientFactory(organization="Quiet Corp", is_active=True)
    body = _team_client().get(f"/api/v1/cockpit/customers/{client_row.id}/").json()
    for forbidden in ("licenseOutProbability", "leadScore", "tier", "personaId"):
        assert forbidden not in body
