"""
KPI-preview builder.

Builds ``kpiPreview`` — a few label/metric pairs that frame *what ALPHA measures*, using
deliberately qualitative, hedged "metrics" (never promised numbers). Matches the web
``KpiPreviewItem`` type ``{label, metric}`` and the claims discipline.
"""

from __future__ import annotations

_BASE_KPIS = [
    {"label": "Representation efficiency", "metric": "Assessed during diagnosis"},
    {"label": "Execution / runtime fit", "metric": "Evaluated against an eligible workload"},
    {"label": "Validated outcome", "metric": "Quantified only via a proof-of-concept"},
]

_ROUTE_KPI = {
    "alpha_compute": {"label": "Where work is avoidable", "metric": "Identified in the Compute review"},
    "alpha_core": {"label": "Data-movement overhead", "metric": "Profiled in the Core review"},
    "both": {"label": "Representation + execution", "metric": "Assessed end-to-end"},
    "general": {"label": "Bottleneck location", "metric": "Located in an initial review"},
}


def build_kpi_preview(*, product_route: str) -> list[dict]:
    route_kpi = _ROUTE_KPI.get(product_route, _ROUTE_KPI["general"])
    # Route-specific KPI first, then the qualitative base set.
    return [route_kpi, *_BASE_KPIS]
