"""
Route distribution.

Counts leads by product route, keyed by the dashboard display strings. Neutral and
ASTOP routes are first-class in the September 2026 product model; historical ``both``
rows remain visible as ``Multiple products`` without being treated as a new progression
shortcut.
"""

from __future__ import annotations

from apps.leads.models import PRODUCT_ROUTE_DISPLAY, Lead


def route_distribution(*, since=None) -> dict:
    dist = {
        "Not yet assessed": 0,
        "ASTOP": 0,
        "ALPHA Compute": 0,
        "ALPHA Core": 0,
        "Multiple products": 0,
    }
    qs = Lead.objects.all()
    if since:
        qs = qs.filter(submitted_at__gte=since)
    for lead in qs.only("product_route"):
        label = PRODUCT_ROUTE_DISPLAY.get(lead.product_route, "Not yet assessed")
        dist[label] = dist.get(label, 0) + 1
    return dist
