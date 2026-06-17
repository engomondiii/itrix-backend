"""Prohibited-language checker tests — claims discipline."""

from __future__ import annotations

from apps.ai_engine.services.prohibited_language_checker import (
    PROHIBITED_CLAIMS,
    contains_prohibited,
    find_violations,
    scrub,
)


def test_detects_each_prohibited_claim():
    for claim in PROHIBITED_CLAIMS:
        text = f"Our product {claim} for you."
        assert contains_prohibited(text), claim


def test_detects_generic_guarantee():
    assert contains_prohibited("We guarantee a 50% reduction.")


def test_detects_absolutes():
    assert contains_prohibited("It is always faster and works for every workload.")


def test_clean_text_passes():
    text = "ALPHA may help with your specific workload, subject to validation."
    assert contains_prohibited(text) is False


def test_scrub_removes_prohibited_claims():
    text = "This guarantees lower power and is always faster."
    scrubbed = scrub(text)
    assert "guarantees lower power" not in scrubbed.lower()
    assert "always faster" not in scrubbed.lower()


def test_find_violations_returns_list():
    violations = find_violations("We guarantee 100% uptime always.")
    assert isinstance(violations, list) and len(violations) > 0
