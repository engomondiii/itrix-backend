"""Canonical ASTOP time-to-first-value semantics and dependent projections."""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.analytics.services import management_reporting
from apps.customer_success.services.astop_integration import snapshot
from apps.leads.models import ASTOPEngagement
from tests.factories.client_factory import ClientFactory
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def _record(*, start=None, end=None):
    return ASTOPEngagement.objects.create(
        lead=LeadFactory(),
        authorized_install_at=start,
        reproducible_value_at=end,
    )


def test_ttfv_missing_authorized_install_is_unavailable():
    record = _record(start=None, end=timezone.now())
    assert record.ttfv_status == "unavailable"
    assert record.ttfv_seconds is None


def test_ttfv_missing_verified_value_timestamp_is_unavailable():
    record = _record(start=timezone.now(), end=None)
    assert record.ttfv_status == "unavailable"
    assert record.ttfv_seconds is None


def test_ttfv_verified_value_before_install_is_invalid_not_zero():
    start = timezone.now()
    record = _record(start=start, end=start - timedelta(seconds=1))
    assert record.ttfv_status == "invalid"
    assert record.ttfv_seconds is None
    assert record.ttfv_seconds != 0


def test_ttfv_equal_valid_timestamps_is_legitimate_zero():
    instant = timezone.now()
    record = _record(start=instant, end=instant)
    assert record.ttfv_status == "valid"
    assert record.ttfv_seconds == 0


def test_ttfv_positive_interval_returns_actual_elapsed_seconds():
    start = timezone.now()
    record = _record(start=start, end=start + timedelta(seconds=91))
    assert record.ttfv_status == "valid"
    assert record.ttfv_seconds == 91


def test_management_reporting_excludes_invalid_and_incomplete_ttfv():
    start = timezone.now()
    _record(start=start, end=start + timedelta(seconds=90))
    _record(start=start, end=None)
    _record(start=start, end=start - timedelta(seconds=3))

    ttfv = management_reporting.summary()["astop"]["ttfv"]

    assert ttfv["validRecordCount"] == 1
    assert ttfv["invalidRecordCount"] == 1
    assert ttfv["unavailableRecordCount"] == 1
    assert ttfv["averageSeconds"] == 90.0
    assert ttfv["minSeconds"] == 90
    assert ttfv["maxSeconds"] == 90


def test_customer_success_does_not_render_invalid_ttfv_as_zero():
    lead = LeadFactory()
    client = ClientFactory(lead=lead)
    start = timezone.now()
    ASTOPEngagement.objects.create(
        lead=lead,
        authorized_install_at=start,
        reproducible_value_at=start - timedelta(seconds=10),
    )

    data = snapshot(client)

    assert data["ttfvSeconds"] is None
    assert data["ttfvSeconds"] != 0


def test_customer_safe_ttfv_never_exposes_negative_duration():
    lead = LeadFactory()
    client = ClientFactory(lead=lead)
    start = timezone.now()
    ASTOPEngagement.objects.create(
        lead=lead,
        authorized_install_at=start,
        reproducible_value_at=start - timedelta(hours=1),
    )

    value = snapshot(client)["ttfvSeconds"]

    assert value is None or value >= 0
