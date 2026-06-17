"""Tier-classifier tests — band boundaries and labels."""

from __future__ import annotations

import pytest

from apps.scoring.services.tier_classifier import (
    TIER_RESPONSE_HOURS,
    classify_tier,
    classify_with_label,
    tier_label,
)


@pytest.mark.parametrize(
    "total,expected_tier",
    [(100, 1), (80, 1), (79, 2), (60, 2), (59, 3), (40, 3), (39, 4), (0, 4)],
)
def test_band_boundaries(total, expected_tier):
    assert classify_tier(total) == expected_tier


def test_labels():
    assert tier_label(1) == "Strategic"
    assert tier_label(2) == "Qualified"
    assert tier_label(3) == "Nurture"
    assert tier_label(4) == "Exploratory"


def test_classify_with_label():
    assert classify_with_label(85) == (1, "Strategic")
    assert classify_with_label(20) == (4, "Exploratory")


def test_response_hours_map():
    assert TIER_RESPONSE_HOURS[1] == 24
    assert TIER_RESPONSE_HOURS[2] == 48
    assert TIER_RESPONSE_HOURS[4] is None
