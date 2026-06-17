"""
Immediate response builder.

When a visitor submits the compute-bottleneck prompt, the site shows an instant,
on-message acknowledgement *before* any AI generation happens (the AI result comes
later, in Phase 2). This service produces that acknowledgement deterministically from
the prompt text and the selected pressure areas.

It mirrors the tone and structure of the web app's local fallback
(``itrix-web/src/lib/content/immediateResponses.ts``) so the experience is identical
whether the response is built here or, on backend failure, on the client.

Pressure areas (must match ``itrix-web`` review config):
    cost · speed · energy · stability_accuracy · memory_data_movement ·
    hardware_utilization · architecture
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.review.services.nda_detector import detect_nda_signals

# Short, hedged reflections per pressure area (claims discipline: no guarantees).
_PRESSURE_REFLECTION: dict[str, str] = {
    "cost": "rising compute spend relative to the output you get back",
    "speed": "turnaround times that are too slow for how you need to work",
    "energy": "power and cooling becoming a hard limit on what you can run",
    "stability_accuracy": "results that drift or lose precision as you scale",
    "memory_data_movement": "data movement dominating the runtime rather than useful work",
    "hardware_utilization": "accelerators that sit underused despite the spend",
    "architecture": "an architecture that is reaching the edge of what it can do",
}

_PRESSURE_LABEL: dict[str, str] = {
    "cost": "cost",
    "speed": "speed",
    "energy": "energy",
    "stability_accuracy": "stability & accuracy",
    "memory_data_movement": "memory & data movement",
    "hardware_utilization": "hardware utilization",
    "architecture": "architecture",
}

_DEFAULT_ACK = (
    "Thank you — we have your description. iTrix looks at whether the computation "
    "is represented in the right form before more hardware is added to it."
)

_NEXT_LINE = (
    "A few short questions will let us map this to ALPHA Compute, ALPHA Core, or both, "
    "and prepare a personalized review."
)


@dataclass
class ImmediateResponse:
    headline: str
    message: str
    reflected_pressures: list[str] = field(default_factory=list)
    nda_reminder: str | None = None

    def to_dict(self) -> dict:
        return {
            "headline": self.headline,
            "message": self.message,
            "reflected_pressures": self.reflected_pressures,
            "nda_reminder": self.nda_reminder,
        }


def _join_human(items: list[str]) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def build_immediate_response(
    prompt: str | None,
    selected_pressures: list[str] | None = None,
) -> ImmediateResponse:
    """Build the instant acknowledgement shown right after prompt submission."""
    pressures = [p for p in (selected_pressures or []) if p in _PRESSURE_REFLECTION]

    if pressures:
        reflections = [_PRESSURE_REFLECTION[p] for p in pressures[:3]]
        labels = [_PRESSURE_LABEL[p] for p in pressures[:3]]
        headline = f"We hear you on {_join_human(labels)}."
        message = (
            "What you're describing sounds like "
            f"{_join_human(reflections)}. {_NEXT_LINE}"
        )
    else:
        headline = "We have your bottleneck."
        message = f"{_DEFAULT_ACK} {_NEXT_LINE}"

    nda = detect_nda_signals(prompt)
    nda_reminder = None
    if nda.nda_recommended:
        nda_reminder = (
            "Please keep details non-confidential for now — we can put an NDA in "
            "place before any deeper technical exchange."
        )

    return ImmediateResponse(
        headline=headline,
        message=message,
        reflected_pressures=pressures,
        nda_reminder=nda_reminder,
    )
