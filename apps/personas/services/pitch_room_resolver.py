"""
Pitch-room resolution (Architecture v2.6 §12.3).

    exact persona_id match  ->  that persona's room
    functional-family match ->  the highest-priority room in the family
    no match                ->  the generic template

The chosen path is RECORDED so the cockpit can tell a tailored room from a fallback —
otherwise "the pitch room was generic" and "the pitch room failed to resolve" look
identical in the data, and only one of those is a bug.

── THE PER-SLIDE DISCLOSURE RULE ────────────────────────────────────────────
Every slide carries its own disclosure level, and the room is filtered against the
subject's CEILING before it renders. A room whose proof slide is nda_only renders its
other slides publicly and omits that one — it does not render a redacted placeholder,
because a visible "[redacted]" tells the visitor something exists that they have not
earned the right to know exists.
"""

from __future__ import annotations

import logging

from apps.personas.models import Persona, PitchRoom
from apps.personas.services.matcher import MATCH_FAMILY, MATCH_GENERIC, PersonaMatch

logger = logging.getLogger("itrix")

# Ceiling ordering used to filter slides.
_CEILING_RANK = {
    "public": 0,
    "controlled_public": 1,
    "nda_only": 2,
    "customer_contract": 3,
    "internal": 4,
}

# The generic room used when nothing matched. Deliberately claim-free: it asks and
# frames, it never asserts. Slide bodies stay at Claim-Card level 1.
GENERIC_ROOM = {
    "pitch_room_id": "PR-GENERIC-01",
    "title": "Where computation may be holding you back",
    "slides": [
        {
            "key": "what_we_heard",
            "title": "What we heard",
            "body": "Here is how we would describe the pressure you brought to us, in your own terms.",
            "disclosure": "public",
        },
        {
            "key": "why_it_matters",
            "title": "Why it matters",
            "body": "AI-scale demand turns small structural inefficiencies into strategic constraints on cost, energy and capacity.",
            "disclosure": "public",
        },
        {
            "key": "hidden_layer",
            "title": "The layer underneath",
            "body": "Much of what looks like a hardware limit begins earlier, in the form the computation reaches the machine in.",
            "disclosure": "public",
        },
        {
            "key": "where_itrix_fits",
            "title": "Where itriX fits",
            "body": "ALPHA Compute diagnoses whether the workload should be represented differently before execution. ALPHA Core tests whether that form can run.",
            "disclosure": "public",
        },
        {
            "key": "proof_plan",
            "title": "How we would prove it",
            "body": "Workload by workload, against a baseline you agree, with the validation boundary stated before we start.",
            "disclosure": "controlled_public",
        },
        {
            "key": "now_vs_nda",
            "title": "What we can discuss now",
            "body": "We can go a long way on non-confidential descriptions. An NDA lets us look at your actual workload structure.",
            "disclosure": "public",
        },
        {
            "key": "next_step",
            "title": "A sensible next step",
            "body": "A Compute Bottleneck Review of one representative workload.",
            "disclosure": "public",
        },
    ],
}


def _slide_allowed(slide: dict, ceiling: str) -> bool:
    slide_level = (slide or {}).get("disclosure") or "public"
    return _CEILING_RANK.get(slide_level, 0) <= _CEILING_RANK.get(ceiling, 0)


def filter_slides(slides: list[dict], ceiling: str) -> list[dict]:
    """
    Drop slides above the subject's ceiling.

    OMITS rather than redacts: a "[redacted]" marker would itself disclose that
    something exists.
    """
    return [slide for slide in (slides or []) if _slide_allowed(slide, ceiling)]


def resolve(match: PersonaMatch, *, ceiling: str = "public") -> dict:
    """
    Resolve a match to a renderable room payload.

    Returns::

        {
          "pitch_room_id", "title", "slides", "match_path",
          "persona_id",        # INTERNAL — strip before any client-plane payload
          "slides_withheld"    # count only, never which
        }
    """
    persona = match.persona if match else None
    room: PitchRoom | None = None

    if persona is not None:
        room = getattr(persona, "pitch_room", None)
        if room is None:
            room = PitchRoom.objects.filter(persona=persona).first()

    if room is None and match and match.family:
        fallback = (
            Persona.objects.filter(functional_family=match.family)
            .exclude(validation_status="rejected")
            .order_by("priority", "persona_id")
            .first()
        )
        if fallback is not None:
            room = PitchRoom.objects.filter(persona=fallback).first()
            if room is not None:
                persona = fallback

    if room is None:
        slides = filter_slides(GENERIC_ROOM["slides"], ceiling)
        return {
            "pitch_room_id": GENERIC_ROOM["pitch_room_id"],
            "title": GENERIC_ROOM["title"],
            "slides": slides,
            "match_path": MATCH_GENERIC,
            "persona_id": None,
            "slides_withheld": len(GENERIC_ROOM["slides"]) - len(slides),
        }

    all_slides = room.slides or []
    slides = filter_slides(all_slides, ceiling)
    return {
        "pitch_room_id": room.pitch_room_id,
        "title": room.title,
        "slides": slides,
        "match_path": match.path if match else MATCH_FAMILY,
        "persona_id": persona.persona_id if persona else None,
        "slides_withheld": len(all_slides) - len(slides),
    }


def resolve_for_lead(lead, *, ceiling: str = "public", example_key: str = "") -> dict:
    """Convenience: match then resolve in one call."""
    from apps.personas.services.matcher import match as match_persona

    return resolve(match_persona(lead, example_key=example_key), ceiling=ceiling)
