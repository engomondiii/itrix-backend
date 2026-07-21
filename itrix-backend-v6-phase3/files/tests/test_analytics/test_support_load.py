"""Support-load aggregate: queue depth, SLA compliance, ageing."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.analytics.services import support_load
from apps.customer_success.models import SupportRequest
from tests.factories.client_factory import ClientFactory
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def client(db):
    c = ClientFactory(lead=LeadFactory(journey_state="ASSESSMENT"))
    c.first_payment_recorded_at = timezone.now()
    c.save(update_fields=["first_payment_recorded_at"])
    return c


def test_queue_depth_counts_open_and_blocking(client):
    SupportRequest.objects.create(client=client, subject="A", blocking=True)
    SupportRequest.objects.create(client=client, subject="B", blocking=False)
    depth = support_load.queue_depth()
    assert depth["open"] == 2
    assert depth["blocking"] == 1


def test_a_resolved_request_leaves_the_queue(client):
    request = SupportRequest.objects.create(client=client, subject="A")
    request.resolved_at = timezone.now()
    request.save(update_fields=["resolved_at"])
    assert support_load.queue_depth()["open"] == 0


def test_an_unanswered_overdue_request_counts_as_a_breach(client):
    """
    THE COUNTING RULE THAT MATTERS. Counting it as pending would let a permanently
    unanswered request stay out of the denominator — compliance would improve by
    ignoring the worst cases.
    """
    SupportRequest.objects.create(
        client=client, subject="Ignored",
        sla_due_at=timezone.now() - timezone.timedelta(hours=2),
    )
    sla = support_load.sla_compliance()
    assert sla["breached"] == 1
    assert sla["met"] == 0


def test_a_request_answered_in_time_counts_as_met(client):
    now = timezone.now()
    SupportRequest.objects.create(
        client=client, subject="Answered",
        sla_due_at=now + timezone.timedelta(hours=2),
        first_response_at=now,
    )
    assert support_load.sla_compliance()["met"] == 1


def test_a_late_answer_counts_as_a_breach(client):
    now = timezone.now()
    SupportRequest.objects.create(
        client=client, subject="Late",
        sla_due_at=now - timezone.timedelta(hours=2),
        first_response_at=now,
    )
    assert support_load.sla_compliance()["breached"] == 1


def test_an_empty_window_reports_no_rate_rather_than_zero(client):
    """0% compliance and "no data" are different stories."""
    assert support_load.sla_compliance()["rate"] is None


def test_ageing_buckets_open_requests(client):
    SupportRequest.objects.create(client=client, subject="Fresh")
    buckets = support_load.ageing()
    assert buckets["under_1d"] == 1


def test_the_oldest_open_list_helps_an_operator_act(client):
    SupportRequest.objects.create(client=client, subject="Waiting", blocking=True)
    oldest = support_load.oldest_open()
    assert oldest and oldest[0]["subject"] == "Waiting"
