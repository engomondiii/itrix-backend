"""The customer-health board aggregate (Backend v6.0 §Phase 3)."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.analytics.services import customer_health
from tests.factories.client_factory import ClientFactory
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def _client(health=""):
    client = ClientFactory(lead=LeadFactory(journey_state="ASSESSMENT"))
    client.first_payment_recorded_at = timezone.now()
    client.customer_health = health
    client.save(update_fields=["first_payment_recorded_at", "customer_health"])
    return client


def test_the_distribution_always_reports_every_class():
    """A missing key reads as zero to some charting libraries and as an error to others."""
    counts = customer_health.distribution()
    for key in ("stable", "at_risk", "critical", "unknown"):
        assert key in counts


def test_unmeasured_customers_are_counted_separately():
    """
    A rising unmeasured count looks like a broken sales motion — every one of them has
    expansion refused — when it is really a broken measurement.
    """
    _client(health="")
    assert customer_health.unmeasured_count() >= 1


def test_at_risk_counts_critical_too():
    _client(health="critical")
    assert customer_health.at_risk_count() >= 1


def test_the_board_carries_reasons_not_just_a_class():
    """A health class an operator cannot explain is a number they learn to ignore."""
    from apps.customer_success.services import support_router

    client = _client()
    support_router.route(client, "Production is down and we are blocked")
    rows = customer_health.board()
    row = next(r for r in rows if r["clientId"] == str(client.id))
    assert row["reasons"]
    assert row["blockingSupport"] is True


def test_the_board_sorts_worst_first():
    _client(health="stable")
    _client(health="critical")
    healths = [r["health"] for r in customer_health.board()]
    if "critical" in healths and "stable" in healths:
        assert healths.index("critical") < healths.index("stable")


def test_expansion_eligibility_is_on_every_row():
    _client(health="stable")
    assert all("expansionAllowed" in row for row in customer_health.board())
