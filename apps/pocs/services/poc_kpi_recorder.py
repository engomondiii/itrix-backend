"""
PoC KPI recorder.

Builds the default KPI rows for a PoC (baseline/target/result) and provides a helper to
record a result against a KPI within the JSON list. Categories mirror the evaluation set.
"""

from __future__ import annotations

_DEFAULT_KPIS = [
    ("Runtime", "Wall-clock time on the agreed workload"),
    ("Memory", "Peak memory / data movement"),
    ("Energy", "Energy per useful result"),
    ("Accuracy", "Numerical accuracy vs the reference"),
    ("Integration", "Integration effort & stability"),
]


def default_kpis() -> list[dict]:
    return [
        {"id": i + 1, "category": cat, "metric": metric, "baseline": "", "target": "", "result": ""}
        for i, (cat, metric) in enumerate(_DEFAULT_KPIS)
    ]


def record_kpi_result(kpis: list[dict], kpi_id, result: str) -> list[dict]:
    for k in kpis:
        if str(k.get("id")) == str(kpi_id):
            k["result"] = result
    return kpis
