"""
The customer health board — ROW-LEVEL (Backend v7.1 §Phase 1).

── THE FIELD RENAMES, AND WHY EACH ONE ─────────────────────────────────────
The 21 July decisions renamed three keys. They look cosmetic and are not:

    board  -> results        ``board`` named the WIDGET. The dashboard already knows it
                             is a board; what it needs from the payload is the rows. A
                             key named after its own UI is a key that cannot be reused by
                             a second view without lying.

    organization -> company  Consistency with every other row-level resource on this
                             surface. One name for one thing.

    health -> healthClass    ``health`` reads like a score. It is a CLASS from a closed
                             set of four, and calling it a class stops an operator
                             reading "at_risk" as a number and stops a chart treating it
                             as ordinal.

── AND healthClass KEEPS FOUR VALUES ───────────────────────────────────────
stable · at_risk · critical · unknown.

``critical`` is NOT collapsed into ``at_risk``. It is the difference between "watch this"
and "someone should call them today", and an operator who cannot see it will treat the
whole board as advisory. ``unknown`` is a real value too, and a rising count of it looks
like a broken sales motion when it is really a broken measurement.

``reasons`` and ``expansionAllowed`` are preserved verbatim. A health class an operator
cannot explain is a number they learn to ignore, and ``expansionAllowed`` is the
customer-first rule as data rather than as a convention.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("itrix")

# The four values. `critical` is never collapsed.
HEALTH_CLASSES: tuple[str, ...] = ("stable", "at_risk", "critical", "unknown")

# Worst first. The board exists to surface who needs attention, so the sort order is
# part of the contract rather than a presentation detail.
_ORDER = {"critical": 0, "at_risk": 1, "unknown": 2, "stable": 3}

DEFAULT_LIMIT = 200
MAX_LIMIT = 500

# ── PAGING A DERIVED SORT (fix, 2026-08-12) ─────────────────────────────────
# Health is computed in Python by `health_calculator.calculate`, not stored, so the
# database cannot order by it. That was already true before paging existed: the old
# `[:limit]` took an arbitrary 200 clients and sorted THOSE worst-first, so "worst
# first" has always meant "worst first within what was fetched".
#
# Paging makes that visible rather than introducing it, and the page order is now a
# STABLE database order (`-created_at, id`) so page 2 cannot repeat or skip a row.
# The payload says `ordering: "worst_first_within_page"` so a dashboard cannot read
# the first row of page 1 as "the customer most at risk" across the whole book.
ORDERING = "worst_first_within_page"


def page(*, limit: int = DEFAULT_LIMIT, offset: int = 0) -> dict:
    """
    Per-customer rows, worst first. TEAM PLANE ONLY.

    Replaces ``analytics.services.customer_health.board()`` as the ROW-LEVEL read. That
    function stays where it is and keeps its shape, because the aggregate endpoint still
    uses it and a rename there would break a deployed chart for no gain.
    """
    from apps.clients.models import Client
    from apps.customer_success.services.health_calculator import calculate

    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    offset = max(0, int(offset or 0))

    active = Client.objects.filter(is_active=True)
    total = active.count()

    rows: list[dict] = []
    window = active.select_related("lead").order_by("-created_at", "id")[offset:offset + limit]
    for client in window:
        assessment = calculate(client)
        health_class = assessment.health or "unknown"
        if health_class not in HEALTH_CLASSES:
            # An unrecognised class resolves to `unknown` rather than being passed
            # through: the dashboard sorts and colours on this value, and a stray string
            # would sort last and read as healthy.
            logger.warning(
                "cockpit.customers: unknown health class %r for client %s",
                health_class, client.id,
            )
            health_class = "unknown"

        rows.append(
            {
                "clientId": str(client.id),
                # organization -> company
                "company": client.organization or "",
                # health -> healthClass, four values, `critical` intact
                "healthClass": health_class,
                # Preserved verbatim: a class an operator cannot explain is a class they
                # learn to ignore.
                "reasons": assessment.reasons,
                "blockingSupport": assessment.blocking_support,
                "outcomesOffPlan": assessment.outcomes_off_plan,
                "negativePulse": assessment.negative_pulse,
                "degradedDeployments": assessment.degraded_deployments,
                # The customer-first rule, as data.
                "expansionAllowed": assessment.permits_expansion,
            }
        )

    rows.sort(key=lambda r: _ORDER.get(r["healthClass"], 9))
    return {
        "results": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
        "hasMore": offset + len(rows) < total,
        "ordering": ORDERING,
    }


def results(*, limit: int = DEFAULT_LIMIT, offset: int = 0) -> list[dict]:
    """
    The customer rows alone — the shape existing callers and tests expect.

    A thin read of `page()`, so there is only one implementation of the query and the
    health computation.
    """
    return page(limit=limit, offset=offset)["results"]


def detail(client_id: str) -> dict | None:
    """
    One customer's health, with the reasons behind it.

    Deliberately does NOT include the licence-out probability, the lead score, the tier or
    any other commercial signal. Those live on the lead and the cockpit lead route; a
    customer-success read that carried them would invite an operator to open a health
    review and leave with an expansion plan, which is the precise inversion the
    customer-first rule exists to prevent.
    """
    from apps.clients.models import Client
    from apps.customer_success.services.health_calculator import calculate

    client = Client.objects.filter(id=client_id, is_active=True).first()
    if client is None:
        return None

    assessment = calculate(client)
    health_class = assessment.health or "unknown"
    if health_class not in HEALTH_CLASSES:
        health_class = "unknown"

    return {
        "clientId": str(client.id),
        "company": client.organization or "",
        "healthClass": health_class,
        "reasons": assessment.reasons,
        "blockingSupport": assessment.blocking_support,
        "outcomesOffPlan": assessment.outcomes_off_plan,
        "negativePulse": assessment.negative_pulse,
        "degradedDeployments": assessment.degraded_deployments,
        "expansionAllowed": assessment.permits_expansion,
        "contractState": getattr(client, "contract_state", "") or "",
    }
