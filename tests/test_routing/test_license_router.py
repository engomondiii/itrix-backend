"""License-router tests."""

from __future__ import annotations

from apps.routing.services.license_router import route_license


def test_exclusive_interest_strategic_for_hardware_org():
    answers = {"Q9": "exclusive", "Q6": "hardware_chip"}
    assert route_license(answers) == "strategic"


def test_exclusive_interest_exclusive_for_other_org():
    answers = {"Q9": "exclusive", "Q6": "enterprise_rd"}
    assert route_license(answers) == "exclusive"


def test_non_exclusive_interest():
    answers = {"Q9": "non_exclusive", "Q6": "research"}
    assert route_license(answers) == "non_exclusive"


def test_product_only_returns_none():
    answers = {"Q9": "product_only", "Q6": "individual"}
    assert route_license(answers) is None


def test_missing_interest_returns_none():
    assert route_license({}) is None
