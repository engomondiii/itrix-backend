"""
Operations fan-out + lifecycle creator tests.

Verifies the Phase 3 wiring: creating a Lead fans out to follow-up + notification + emails,
and the lifecycle creators (NDA / evaluation / PoC) build the right records.
"""

from __future__ import annotations

import pytest
from django.test import override_settings

from apps.emails.models import EmailLog
from apps.follow_up.models import FollowUpTask
from apps.notifications.models import Notification
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


@override_settings(ENABLE_EMAIL_DELIVERY=False)
def test_lead_creation_fans_out():
    lead = LeadFactory(tier=1, email="cto@chipco.example", company="ChipCo")
    # Follow-up task created (Tier 1 has an SLA).
    assert FollowUpTask.objects.filter(lead=lead).count() == 1
    # Notification created (Tier 1 → tier1_lead).
    assert Notification.objects.filter(lead=lead, kind=Notification.Kind.TIER1_LEAD).exists()
    # Internal alert + confirmation emails (stubbed) created.
    kinds = set(EmailLog.objects.filter(lead=lead).values_list("kind", flat=True))
    assert EmailLog.Kind.INTERNAL_ALERT in kinds
    assert EmailLog.Kind.CONFIRMATION in kinds  # has email → confirmation sent


def test_tier4_lead_gets_no_followup_task():
    lead = LeadFactory(tier=4)
    assert FollowUpTask.objects.filter(lead=lead).count() == 0


def test_nda_creator_idempotent():
    from apps.nda.services.nda_creator import create_nda_for_lead

    lead = LeadFactory()
    a = create_nda_for_lead(lead)
    b = create_nda_for_lead(lead)
    assert a.id == b.id
    assert len(a.checklist) == 6


def test_evaluation_creator_selects_package_by_route():
    from apps.evaluations.services.evaluation_creator import create_evaluation_for_lead

    lead = LeadFactory(product_route="alpha_core")
    ev = create_evaluation_for_lead(lead)
    assert ev.pkg == "ALPHA Core Runtime Fit Assessment"
    assert len(ev.kpis) >= 5


def test_poc_creator_seeds_milestones_and_kpis():
    from apps.pocs.services.poc_creator import create_poc_for_lead

    lead = LeadFactory()
    poc = create_poc_for_lead(lead)
    assert len(poc.milestones) == 6
    assert len(poc.kpis) == 5
    assert poc.risks == []


def test_sla_calculator_due_times():
    from apps.follow_up.services.sla_calculator import due_at_for_tier, sla_hours_for_tier

    assert sla_hours_for_tier(1) == 24
    assert sla_hours_for_tier(4) is None
    assert due_at_for_tier(4) is None
    assert due_at_for_tier(1) is not None
