"""Diagnosis agent + the rag_pipeline compatibility shim."""

from __future__ import annotations

import pytest

from apps.agents.services.context import AgentContext
from apps.agents.services.diagnosis import DiagnosisAgent

pytestmark = pytest.mark.django_db


def test_diagnosis_fallback_is_empty(settings):
    settings.ENABLE_AGENTS = False
    settings.ENABLE_AI_ENGINE = False
    out = DiagnosisAgent().run(AgentContext(prompt="p", product_route="general"))
    assert out.is_empty()
    assert out.used_ai is False


def test_rag_pipeline_shim_still_importable(settings):
    # The old import path must keep working (thin shim over the Diagnosis agent).
    settings.ENABLE_AI_ENGINE = False
    from apps.ai_engine.services.rag_pipeline import RagResult, generate_result_partial, run_rag

    result = run_rag(
        prompt="my workload is expensive",
        product_route="alpha_compute",
        license_pathway=None,
        tier=2,
        pressures=["cost"],
    )
    assert isinstance(result, RagResult)
    assert result.used_ai is False  # engine off → deterministic
    assert result.partial == {}
    assert generate_result_partial(
        prompt="x", product_route="general", license_pathway=None, tier=4, pressures=[]
    ) == {}
