"""
KPI framework builder.

Builds the default KPI rows for an evaluation, tuned to the package. Categories match the
dashboard's expected set (Runtime, Memory, Energy, Accuracy, Reproducibility, Integration).
Targets/results start empty and are filled in as the evaluation progresses.
"""

from __future__ import annotations

_BASE = [
    ("Runtime", "Wall-clock time on the agreed workload"),
    ("Memory", "Peak memory / data-movement profile"),
    ("Accuracy", "Numerical accuracy vs the reference"),
    ("Reproducibility", "Run-to-run consistency"),
    ("Integration", "Effort to integrate into the existing stack"),
]

_ENERGY = ("Energy", "Energy per useful result")


def build_kpi_framework(product_route: str) -> list[dict]:
    rows = list(_BASE)
    # Core / hardware-leaning evaluations also track energy explicitly.
    if product_route in ("alpha_core", "both"):
        rows.insert(2, _ENERGY)
    return [
        {"id": i + 1, "category": cat, "metric": metric, "target": "", "result": ""}
        for i, (cat, metric) in enumerate(rows)
    ]
