"""
Route distribution.

Counts leads by product route, keyed by the dashboard's display strings
("ALPHA Compute" / "ALPHA Core" / "Both") so it maps directly onto
``OverviewMetrics.routeDistribution: Record<ProductRoute, number>``.
"""

from __future__ import annotations

from apps.leads.models import PRODUCT_ROUTE_DISPLAY, Lead


def route_distribution(*, since=None) -> dict:
    dist = {"ALPHA Compute": 0, "ALPHA Core": 0, "Both": 0}
    qs = Lead.objects.all()
    if since:
        qs = qs.filter(submitted_at__gte=since)
    for lead in qs.only("product_route"):
        label = PRODUCT_ROUTE_DISPLAY.get(lead.product_route, "ALPHA Compute")
        dist[label] = dist.get(label, 0) + 1
    return dist
