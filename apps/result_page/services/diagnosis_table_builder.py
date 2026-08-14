"""
Diagnosis-table builder.

Builds ``diagnosis`` — one row per pressure area the visitor selected, each with the
observation, itriX's interpretation, and the ALPHA role. Matches the web ``DiagnosisRow``
type: ``{pressure, observation, itrixInterpretation, alphaRole}``. Deterministic; the AI
path may replace this with a richer version, falling back to this when absent.
"""

from __future__ import annotations

# Per-pressure diagnostic content. ``pressure`` keys match the web PressureArea values.
_DIAGNOSIS = {
    "cost": {
        "observation": "Compute spend rises roughly in step with workload, with little headroom.",
        "itrixInterpretation": "Cost scaling like this usually signals an inefficient representation, not just under-provisioned hardware.",
        "alphaRole": "ALPHA Compute diagnoses where the representation is doing avoidable work.",
    },
    "speed": {
        "observation": "Runtime is too slow for the iteration cadence you need.",
        "itrixInterpretation": "Latency is often set by how the computation is structured before it is set by raw hardware speed.",
        "alphaRole": "ALPHA Compute can diagnose, transform and validate the software execution route; ALPHA Core is optional for deeper hardware acceleration.",
    },
    "energy": {
        "observation": "Power or cooling is a binding constraint on how much you can run.",
        "itrixInterpretation": "Energy per useful result is a function of representation efficiency, not only of the chip.",
        "alphaRole": "ALPHA looks for representations that need fewer operations per result.",
    },
    "stability_accuracy": {
        "observation": "Numerical stability or accuracy degrades as the problem scales.",
        "itrixInterpretation": "Drift at scale frequently traces back to how state and dynamics are represented.",
        "alphaRole": "ALPHA Compute includes transformation, execution/routing, verification and reconstruction in software; ALPHA Core is optional hardware implementation.",
    },
    "memory_data_movement": {
        "observation": "Most of the runtime is spent moving data rather than computing on it.",
        "itrixInterpretation": "Data-movement-bound runtimes usually point to an execution/runtime issue.",
        "alphaRole": "ALPHA Compute evaluates whether representation and software execution can reduce avoidable movement; ALPHA Core is considered only for additional hardware-level value.",
    },
    "hardware_utilization": {
        "observation": "Accelerators are underused relative to what you're paying for.",
        "itrixInterpretation": "Low utilisation is typically an execution-mapping problem, not a capacity problem.",
        "alphaRole": "ALPHA Compute establishes and validates the software route on existing hardware; ALPHA Core can later implement validated structures more deeply in hardware.",
    },
    "architecture": {
        "observation": "You keep hitting the same ceiling regardless of incremental tuning.",
        "itrixInterpretation": "A persistent ceiling often indicates a representational limit rather than an implementation bug.",
        "alphaRole": "ALPHA Compute assesses whether a different representation changes the ceiling.",
    },
}

_DEFAULT_ROW = {
    "observation": "A computation bottleneck is limiting throughput or cost.",
    "itrixInterpretation": "Bottlenecks like this usually begin in representation before they are about scale.",
    "alphaRole": "ALPHA Compute provides the software path from diagnosis and eligibility through transformation, verification and measured deployment.",
}


def build_diagnosis(*, pressures: list[str]) -> list[dict]:
    """Return the structural-diagnosis rows for the selected pressures."""
    rows: list[dict] = []
    seen = set()
    for pressure in pressures or []:
        if pressure in seen:
            continue
        seen.add(pressure)
        content = _DIAGNOSIS.get(pressure, _DEFAULT_ROW)
        rows.append({"pressure": pressure, **content})

    if not rows:
        rows.append({"pressure": "cost", **_DEFAULT_ROW})
    return rows
