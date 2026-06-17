"""
Problem-mirror builder.

Builds ``problemMirror`` — a short paragraph that reflects the visitor's stated problem
back to them in itriX's framing (representation vs execution), establishing that we
understood them before proposing anything. Deterministic; used directly when the AI engine
is off, or as the fallback when the AI didn't supply this field.
"""

from __future__ import annotations

_PRESSURE_PHRASE = {
    "cost": "compute cost that grows faster than the value you get from it",
    "speed": "turnaround that's too slow for how you need to work",
    "energy": "power and cooling limits pressing on your compute",
    "stability_accuracy": "stability or accuracy that drifts as you scale",
    "memory_data_movement": "runtime dominated by moving data rather than computing on it",
    "hardware_utilization": "expensive accelerators sitting underused",
    "architecture": "an architectural ceiling you keep running into",
}


def build_problem_mirror(*, prompt: str, pressures: list[str], product_route: str) -> str:
    """Return the problem-mirror narrative."""
    pains = [_PRESSURE_PHRASE.get(p) for p in (pressures or []) if p in _PRESSURE_PHRASE]
    pains = [p for p in pains if p]

    if pains:
        if len(pains) == 1:
            pain_clause = pains[0]
        else:
            pain_clause = ", ".join(pains[:-1]) + f", and {pains[-1]}"
        lead_in = f"You're describing {pain_clause}."
    else:
        lead_in = "You're describing a computation bottleneck that's holding back what you're trying to do."

    if product_route == "alpha_core":
        frame = (
            " That pattern usually isn't a question of buying more hardware — it's how the "
            "computation executes against the hardware you already have."
        )
    elif product_route == "both":
        frame = (
            " That pattern usually sits across both how the problem is represented and how it "
            "executes — which is exactly where ALPHA looks first."
        )
    else:
        frame = (
            " In our experience that pattern usually starts with how the problem is represented, "
            "before it's ever a question of scale."
        )

    return (lead_in + frame).strip()
