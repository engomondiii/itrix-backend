"""Persona matching (Backend v6.0 §1.3, Architecture v2.6 §12.3)."""

from __future__ import annotations

import pytest

from apps.personas.models import FunctionalFamily, Persona
from apps.personas.services.matcher import (
    MATCH_EXACT,
    MATCH_FAMILY,
    MATCH_GENERIC,
    infer_family,
    match,
    match_company,
)
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    Persona.objects.create(
        persona_id="P-T01",
        company="NVIDIA",
        department="Silicon Software",
        functional_family=FunctionalFamily.SILICON_MEMORY_HARDWARE,
        priority=1,
    )
    Persona.objects.create(
        persona_id="P-T02",
        company="NVIDIA",
        department="Cloud Infra",
        functional_family=FunctionalFamily.CLOUD_INFRASTRUCTURE,
        priority=1,
    )
    Persona.objects.create(
        persona_id="P-T03",
        company="Acme HPC",
        department="Simulation",
        functional_family=FunctionalFamily.RUNTIME_HPC_SIMULATION,
        priority=2,
    )


def test_selected_example_is_a_strong_prior():
    """The visitor chose it deliberately, so it outranks our reading of their words."""
    family, confidence = infer_family(example_key="runtime_hpc_simulation")
    assert family == FunctionalFamily.RUNTIME_HPC_SIMULATION.value
    assert confidence >= 0.8


def test_keyword_inference_is_deliberately_weak():
    """
    Our reading of their prose is a signal about PROBLEM SHAPE, not organisation. It
    must never be confident enough on its own to promote an exact match.
    """
    family, confidence = infer_family(prompt="our CFD solver drifts over long simulations")
    assert family == FunctionalFamily.RUNTIME_HPC_SIMULATION.value
    assert confidence <= 0.55


def test_no_signal_yields_no_family():
    assert infer_family(prompt="hello") == (None, 0.0)


def test_company_normalisation_ignores_legal_suffixes(seeded):
    assert match_company("NVIDIA Corporation")
    assert match_company("nvidia")
    assert match_company("NVIDIA, Inc.")


def test_company_plus_confident_family_yields_an_exact_match(seeded):
    lead = LeadFactory(company="NVIDIA")
    result = match(lead, example_key="silicon_memory_hardware")
    assert result.path == MATCH_EXACT
    assert result.persona.persona_id == "P-T01"


def test_company_with_weak_family_stays_at_family_level(seeded):
    """
    A weak prior must not be promoted just because the company matched. Getting the
    department wrong inside the right account is worse than not guessing.
    """
    lead = LeadFactory(company="NVIDIA", compute_bottleneck="our solver is slow")
    result = match(lead)
    assert result.path == MATCH_FAMILY


def test_no_signal_falls_back_to_generic(seeded):
    lead = LeadFactory(company="Nobody In The Registry", compute_bottleneck="hello")
    result = match(lead)
    assert result.path == MATCH_GENERIC
    assert result.persona is None


def test_the_digest_is_internal_only_and_carries_the_path(seeded):
    lead = LeadFactory(company="NVIDIA")
    digest = match(lead, example_key="silicon_memory_hardware").digest()
    assert digest["persona_id"] == "P-T01"
    assert digest["match_path"] == MATCH_EXACT
    assert "confidence" in digest


def test_rejected_personas_are_never_matched(seeded):
    Persona.objects.filter(persona_id="P-T01").update(validation_status="rejected")
    lead = LeadFactory(company="NVIDIA")
    result = match(lead, example_key="silicon_memory_hardware")
    assert result.persona is None or result.persona.persona_id != "P-T01"
