"""Claim checker: threshold matrix, scrubbing, hard-block, canonical wording."""

from __future__ import annotations

import pytest

from apps.governance.services.claim_checker import (
    GOV_AUTO_APPROVED,
    GOV_PENDING,
    check,
)

pytestmark = pytest.mark.django_db


def test_low_claim_level_auto_approves(settings):
    settings.AGENT_AUTO_APPROVE_MAX_LEVEL = 2
    assert check("A qualitative fit note.", claim_level=1).status == GOV_AUTO_APPROVED
    assert check("A qualitative fit note.", claim_level=2).status == GOV_AUTO_APPROVED


def test_high_claim_level_pends(settings):
    settings.AGENT_AUTO_APPROVE_MAX_LEVEL = 2
    assert check("A draft.", claim_level=3).status == GOV_PENDING
    d5 = check("A term sheet outline.", claim_level=5)
    assert d5.status == GOV_PENDING
    assert d5.requires_second_approver is True


def test_prohibited_language_is_scrubbed():
    d = check("This guarantees lower power and always works.", claim_level=1)
    assert "guarantee" not in d.text.lower()


def test_alpha_core_canonical_wording_enforced():
    d = check("ALPHA Core uses a lookup table execution model.", claim_level=1)
    assert "table-free index-ordered algebraic execution" in d.text


def test_benchmark_claim_forced_to_human_review():
    d = check("It is 10x faster than the competition.", claim_level=1)
    assert d.status == GOV_PENDING
    assert d.requires_second_approver is True
