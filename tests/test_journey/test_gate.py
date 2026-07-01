"""Deterministic gates: invite eligibility + value-first enforcement."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.journey.services.gate import account_invite_allowed, commitment_allowed
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def test_tier_1_and_2_always_invite_allowed():
    assert account_invite_allowed(LeadFactory(tier=1)) is True
    assert account_invite_allowed(LeadFactory(tier=2)) is True


def test_low_tier_no_intent_not_allowed():
    lead = LeadFactory(tier=4, commercial_intent="", special_rights="None")
    assert account_invite_allowed(lead) is False


def test_strong_intent_overrides_low_tier():
    lead = LeadFactory(tier=4, commercial_intent="paid_assessment")
    assert account_invite_allowed(lead) is True


def test_special_rights_overrides_low_tier():
    lead = LeadFactory(tier=4, commercial_intent="", special_rights="Field")
    assert account_invite_allowed(lead) is True


def test_value_first_blocks_ask_before_value():
    lead = LeadFactory(tier=1, value_delivered_at=None)
    assert commitment_allowed(lead, "nda") is False


def test_value_first_allows_after_value():
    lead = LeadFactory(tier=1, value_delivered_at=timezone.now())
    assert commitment_allowed(lead, "nda") is True


def test_account_creation_requires_invite_gate_and_value():
    lead = LeadFactory(tier=4, commercial_intent="", value_delivered_at=timezone.now())
    assert commitment_allowed(lead, "account_creation") is False


def test_unknown_ask_is_refused():
    lead = LeadFactory(tier=1, value_delivered_at=timezone.now())
    assert commitment_allowed(lead, "buy_now") is False
