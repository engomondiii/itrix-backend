"""Hallucination-guard tests — scrubbing + grounding of quantitative claims."""

from __future__ import annotations

from apps.ai_engine.services.hallucination_guard import guard, is_safe


def test_removes_prohibited_language():
    report = guard("We guarantee lower power for every workload.")
    assert report.changed is True
    assert "guarantee" not in report.text.lower()


def test_hedges_unsupported_quantitative_claim():
    report = guard("ALPHA makes it 40% faster.", evidence="general qualitative context")
    assert "40%" not in report.text
    assert "40%" in report.quant_hedged


def test_keeps_supported_quantitative_claim():
    # If the number appears in the evidence, it may stay.
    report = guard("Benchmarks showed 40% improvement.", evidence="the workload showed 40% improvement")
    assert "40%" in report.text


def test_clean_text_is_safe():
    assert is_safe("ALPHA may help in eligible cases, subject to validation.") is True


def test_empty_text():
    report = guard("")
    assert report.text == ""
    assert report.changed is False
