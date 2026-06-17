"""
Prompt handler.

Orchestrates the "visitor submitted the bottleneck prompt" step:

1. validate & clean the prompt text,
2. persist it on the ``ReviewSession`` (prompt, pressure areas, environment),
3. run NDA detection and stash the result,
4. build the immediate on-message acknowledgement.

This keeps the view thin and makes the behaviour unit-testable without HTTP.
The AI-generated result is a *separate*, later step (Phase 2).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from apps.core.validators import clean_text, validate_prompt
from apps.review.services.immediate_response import ImmediateResponse, build_immediate_response
from apps.review.services.nda_detector import detect_nda_signals

logger = logging.getLogger("itrix")

# Must match itrix-web review config pressure-area values.
VALID_PRESSURE_AREAS = {
    "cost",
    "speed",
    "energy",
    "stability_accuracy",
    "memory_data_movement",
    "hardware_utilization",
    "architecture",
}


@dataclass
class PromptResult:
    session: "object"  # apps.review.models.ReviewSession (avoid import cycle)
    immediate_response: ImmediateResponse
    nda_recommended: bool


def handle_prompt(
    session,
    *,
    prompt: str,
    pressure_areas: list[str] | None = None,
    environment: str | None = None,
) -> PromptResult:
    """Process and persist a submitted prompt; return the immediate response."""
    cleaned_prompt = validate_prompt(prompt)
    pressures = [p for p in (pressure_areas or []) if p in VALID_PRESSURE_AREAS]
    env = clean_text(environment, max_length=64) or ""

    nda = detect_nda_signals(cleaned_prompt)

    session.prompt = cleaned_prompt
    session.pressure_areas = pressures
    session.environment = env
    session.nda_recommended = nda.nda_recommended
    session.nda_signals = nda.matched_signals
    if session.status == session.Status.STARTED:
        session.status = session.Status.PROMPTED
    session.save(
        update_fields=[
            "prompt",
            "pressure_areas",
            "environment",
            "nda_recommended",
            "nda_signals",
            "status",
            "updated_at",
        ]
    )

    immediate = build_immediate_response(cleaned_prompt, pressures)
    logger.info(
        "Prompt handled for review %s (pressures=%s, nda=%s)",
        session.id,
        pressures,
        nda.nda_recommended,
    )
    return PromptResult(
        session=session,
        immediate_response=immediate,
        nda_recommended=nda.nda_recommended,
    )
