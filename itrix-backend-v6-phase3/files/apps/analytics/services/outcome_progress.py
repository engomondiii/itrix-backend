"""
Outcome status distribution (Backend v6.0 §Phase 3, Playbook §12B).

Reports the four approved status words as counts. Deliberately NOT a percentage complete
and NOT a trend line: an outcome is on plan, at risk, off plan or achieved, and any
derived metric would invite somebody to describe "off plan" as "62% of the way there".
"""

from __future__ import annotations

import logging

logger = logging.getLogger("itrix")


def distribution(*, client=None) -> dict:
    from django.db.models import Count

    from apps.customer_success.models import Outcome, OutcomeStatus

    qs = Outcome.objects.all()
    if client is not None:
        qs = qs.filter(client=client)

    counts = {row["status"]: row["n"] for row in qs.values("status").annotate(n=Count("id"))}
    return {choice[0]: counts.get(choice[0], 0) for choice in OutcomeStatus.choices}


def off_plan_customers(*, limit: int = 50) -> list[dict]:
    """
    Customers with at least one outcome off plan or at risk.

    This is the population the customer-first rule is protecting: every one of them has a
    commercial motion suppressed until the outcome recovers.
    """
    from apps.customer_success.models import Outcome, OutcomeStatus

    rows: dict[str, dict] = {}
    qs = (
        Outcome.objects.filter(
            status__in=[OutcomeStatus.OFF_PLAN, OutcomeStatus.AT_RISK]
        )
        .select_related("client")
        .order_by("target_date")[:limit * 4]
    )
    for outcome in qs:
        key = str(outcome.client_id)
        row = rows.setdefault(key, {
            "clientId": key,
            "organization": getattr(outcome.client, "organization", "") or "",
            "outcomes": [],
        })
        row["outcomes"].append({
            "title": outcome.title,
            "status": outcome.status,
            "statusLabel": outcome.get_status_display(),
            "targetDate": outcome.target_date.isoformat() if outcome.target_date else None,
        })
    return list(rows.values())[:limit]


def achievement_rate() -> dict:
    """
    Achieved vs everything else.

    Reported as a raw pair rather than a single percentage so a small denominator is
    visible: 1 of 2 achieved is not the same story as 500 of 1000.
    """
    from apps.customer_success.models import Outcome, OutcomeStatus

    total = Outcome.objects.count()
    achieved = Outcome.objects.filter(status=OutcomeStatus.ACHIEVED).count()
    return {"achieved": achieved, "total": total,
            "rate": round(achieved / total, 3) if total else None}


def summary() -> dict:
    return {
        "distribution": distribution(),
        "achievement": achievement_rate(),
        "offPlanCustomers": off_plan_customers(),
    }
