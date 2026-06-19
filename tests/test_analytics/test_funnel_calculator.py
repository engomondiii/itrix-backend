"""Analytics tests — funnel + overview + endpoint."""

from __future__ import annotations

import pytest

from apps.analytics.services.funnel_calculator import funnel
from apps.analytics.services.overview_aggregator import overview
from apps.analytics.services.route_distribution import route_distribution
from apps.analytics.services.submission_trend import submission_trend
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def test_funnel_stages_present_and_monotonic():
    LeadFactory.create_batch(3, status="New")
    LeadFactory.create_batch(2, status="Contacted")
    LeadFactory(status="Licensed")
    stages = funnel()
    labels = [s["stage"] for s in stages]
    assert labels == ["Submitted", "Contacted", "Meeting / NDA", "Evaluation / PoC", "Licensed"]
    counts = [s["count"] for s in stages]
    # Cumulative "reached or beyond" → non-increasing down the funnel.
    assert counts == sorted(counts, reverse=True)
    assert counts[0] == 6  # total leads


def test_funnel_conversion_present_after_first_stage():
    LeadFactory.create_batch(2, status="New")
    stages = funnel()
    assert "conversion" not in stages[0]
    assert "conversion" in stages[1]


def test_overview_shape_matches_dashboard():
    LeadFactory(tier=1, status="New")
    LeadFactory(tier=2, status="New")
    o = overview(days=30)
    assert set(o.keys()) == {
        "newLeads", "tier1Count", "tier2Count", "overdueFollowUps",
        "tierDistribution", "routeDistribution", "weeklySubmissions",
    }
    assert o["tier1Count"] == 1
    assert o["tier2Count"] == 1


def test_route_distribution_keys_are_display_strings():
    LeadFactory(product_route="alpha_compute")
    LeadFactory(product_route="alpha_core")
    LeadFactory(product_route="both")
    dist = route_distribution()
    assert set(dist.keys()) == {"ALPHA Compute", "ALPHA Core", "Both"}
    assert dist["ALPHA Compute"] >= 1


def test_submission_trend_is_continuous():
    LeadFactory()
    series = submission_trend(days=7)
    assert len(series) == 7
    assert all("date" in p and "count" in p for p in series)


def test_analytics_endpoint_returns_all_blocks(api_client):
    from tests.factories.user_factory import AdminUserFactory, DEFAULT_PASSWORD

    LeadFactory.create_batch(2)
    AdminUserFactory(email="an@itrix.example", name="An")
    login = api_client.post(
        "/api/v1/auth/login/",
        {"email": "an@itrix.example", "password": DEFAULT_PASSWORD},
        format="json",
    ).json()
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login['access']}")
    resp = api_client.get("/api/v1/analytics/?days=30")
    assert resp.status_code == 200
    assert set(resp.json().keys()) == {
        "overview", "funnel", "sla_compliance", "patterns",
        "industry_breakdown", "route_distribution", "submission_trend",
    }


def test_response_time_metrics_shape():
    from apps.analytics.services.sla_compliance_calculator import response_time_metrics

    metrics = response_time_metrics()
    assert set(metrics.keys()) == {
        "tier1AvgHours", "tier2AvgHours", "tier1Breaches", "tier2Breaches", "complianceRate",
    }
