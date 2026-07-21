"""Pitch room resolution and per-slide disclosure filtering."""

from __future__ import annotations

import pytest

from apps.personas.models import FunctionalFamily, Persona, PitchRoom
from apps.personas.services.matcher import MATCH_GENERIC, PersonaMatch
from apps.personas.services.pitch_room_resolver import (
    GENERIC_ROOM,
    filter_slides,
    resolve,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def room():
    persona = Persona.objects.create(
        persona_id="P-R01",
        company="Acme",
        functional_family=FunctionalFamily.AI_MODEL_SYSTEMS,
        priority=1,
    )
    PitchRoom.objects.create(
        pitch_room_id="PR-ACM-01",
        persona=persona,
        title="Acme room",
        slides=[
            {"key": "a", "title": "What we heard", "body": "...", "disclosure": "public"},
            {"key": "b", "title": "Proof plan", "body": "...", "disclosure": "nda_only"},
        ],
    )
    return persona


def test_public_ceiling_omits_the_nda_slide(room):
    result = resolve(PersonaMatch(persona=room, path="exact", confidence=0.9), ceiling="public")
    titles = [s["title"] for s in result["slides"]]
    assert "What we heard" in titles
    assert "Proof plan" not in titles
    assert result["slides_withheld"] == 1


def test_nda_ceiling_includes_every_slide(room):
    result = resolve(PersonaMatch(persona=room, path="exact", confidence=0.9), ceiling="nda_only")
    assert len(result["slides"]) == 2
    assert result["slides_withheld"] == 0


def test_withheld_slides_are_omitted_not_redacted(room):
    """
    A visible '[redacted]' would itself disclose that something exists. Omission tells
    the visitor nothing.
    """
    result = resolve(PersonaMatch(persona=room, path="exact", confidence=0.9), ceiling="public")
    rendered = str(result["slides"])
    assert "redact" not in rendered.lower()
    assert "nda_only" not in rendered


def test_no_match_resolves_to_the_generic_room():
    result = resolve(PersonaMatch(persona=None, path=MATCH_GENERIC, confidence=0.0))
    assert result["pitch_room_id"] == GENERIC_ROOM["pitch_room_id"]
    assert result["persona_id"] is None


def test_the_generic_room_makes_no_quantitative_claim():
    """It asks and frames; it never asserts. Slide bodies stay at claim level 1."""
    import re

    for slide in GENERIC_ROOM["slides"]:
        body = slide["body"]
        assert not re.search(r"\d+\s?%", body), f"generic slide has a figure: {body}"
        assert "guarantee" not in body.lower()


def test_filter_slides_defaults_unlabelled_slides_to_public():
    slides = [{"title": "x", "body": "y"}]
    assert len(filter_slides(slides, "public")) == 1
