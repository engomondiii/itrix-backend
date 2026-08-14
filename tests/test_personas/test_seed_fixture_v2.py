"""Pins the August 2026 60-persona technical-redline workbook in the seed fixture."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.core.management import call_command

from apps.personas.models import Persona

pytestmark = pytest.mark.django_db

FIXTURE = Path(__file__).resolve().parents[2] / "apps" / "personas" / "fixtures" / "personas_60.json"


def test_v2_fixture_contains_all_60_personas_and_proof_contract_fields():
    records = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(records) == 60
    assert len({r["persona_id"] for r in records}) == 60
    for record in records:
        assert record["eligibility_gate"].strip()
        assert record["proof_contract"].strip()
        assert record["expansion_rule"].strip()
        assert len(record["slides"]) == 7


def test_seed_persists_v2_eligibility_and_expansion_contracts():
    call_command("seed_personas")
    persona = Persona.objects.get(persona_id="P-001")
    assert "AXIOM-TENSOR" in persona.eligibility_gate
    assert persona.proof_contract
    assert persona.expansion_rule
    # The redline replaced broad outcome promises with bounded, eligibility-first copy.
    assert "screen one" in persona.response_angle.lower()
