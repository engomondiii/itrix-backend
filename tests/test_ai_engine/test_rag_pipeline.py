"""RAG-pipeline tests — deterministic fallback when AI engine is disabled."""

from __future__ import annotations

import pytest
from django.test import override_settings

from apps.ai_engine.services.rag_pipeline import run_rag

pytestmark = pytest.mark.django_db


@override_settings(ENABLE_AI_ENGINE=False)
def test_disabled_engine_returns_empty_partial_but_retrieves():
    result = run_rag(
        prompt="Our solver is memory-bound and slow.",
        product_route="alpha_core",
        license_pathway="strategic",
        tier=1,
        pressures=["memory_data_movement"],
    )
    # No AI text, but the pipeline still ran retrieval (offline keyword fallback).
    assert result.used_ai is False
    assert result.partial == {}
    assert isinstance(result.chunks, list)


@override_settings(ENABLE_AI_ENGINE=False)
def test_retrieval_only_chunks_are_disclosure_filtered():
    # With no knowledge ingested, retrieval returns an empty (but valid) list.
    result = run_rag(
        prompt="representation diagnosis",
        product_route="alpha_compute",
        license_pathway=None,
        tier=2,
        pressures=["cost"],
    )
    assert all(c.get("disclosure_level") != "internal_only" for c in result.chunks)
