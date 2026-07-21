"""
The customer-health board aggregate (Backend v6.0 §Phase 3, Surface 2 v5.0).

INTERNAL-ONLY in its entirety. ``customer_health`` is on the §10.5 list of fields that
must not appear on the anonymous or client plane at any state, so this module is only
ever reachable behind a team-JWT endpoint.

── AN AGGREGATE THAT CAN BE FILTERED TO ONE CUSTOMER IS THAT CUSTOMER'S RECORD ──
The distribution below is safe. The per-customer rows are not, which is why they are
returned by a separate function that names its audience.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("itrix")


def distribution() -> dict:
    """Health-class counts across the book. Safe to chart."""
    from django.db.models import Count

    from apps.clients.models import Client

    rows = (
        Client.objects.filter(is_active=True)
        .values("customer_health")
        .annotate(n=Count("id"))
    )
    counts = {(row["customer_health"] or "unknown"): row["n"] for row in rows}
    for key in ("stable", "at_risk", "critical", "unknown"):
        counts.setdefault(key, 0)
    return counts


def board(*, limit: int = 200) -> list[dict]:
    """
    Per-customer rows for the health board. TEAM PLANE ONLY.

    Each row carries the REASONS, not just the class. A health class an operator cannot
    explain is a number they will learn to ignore.
    """
    from apps.clients.models import Client
    from apps.customer_success.services.health_calculator import calculate

    rows: list[dict] = []
    for client in Client.objects.filter(is_active=True).select_related("lead")[:limit]:
        assessment = calculate(client)
        rows.append({
            "clientId": str(client.id),
            "organization": client.organization or "",
            "health": assessment.health or "unknown",
            "reasons": assessment.reasons,
            "blockingSupport": assessment.blocking_support,
            "outcomesOffPlan": assessment.outcomes_off_plan,
            "negativePulse": assessment.negative_pulse,
            "degradedDeployments": assessment.degraded_deployments,
            "expansionAllowed": assessment.permits_expansion,
        })
    # Worst first — the board exists to surface who needs attention.
    order = {"critical": 0, "at_risk": 1, "unknown": 2, "stable": 3}
    rows.sort(key=lambda r: order.get(r["health"], 9))
    return rows


def at_risk_count() -> int:
    from apps.clients.models import Client

    return Client.objects.filter(
        is_active=True, customer_health__in=["at_risk", "critical"]
    ).count()


def unmeasured_count() -> int:
    """
    Customers whose health has never been computed.

    Worth watching on its own: an unmeasured customer is one the expansion gate will
    always refuse, so a rising number here looks like a broken sales motion when it is
    really a broken measurement.
    """
    from apps.clients.models import Client

    return Client.objects.filter(is_active=True).filter(customer_health="").count()


def summary() -> dict:
    return {
        "distribution": distribution(),
        "atRisk": at_risk_count(),
        "unmeasured": unmeasured_count(),
    }
