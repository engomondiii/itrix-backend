"""
Support-load aggregate: queue depth, SLA compliance, ageing
(Backend v6.0 §Phase 3, Playbook §12D).

SLA compliance is the number that matters. A breach is worse than a slow response,
because the customer was TOLD a time — the promise is what makes the miss expensive.
"""

from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger("itrix")

AGEING_BUCKETS = ((0, 1, "under_1d"), (1, 3, "1_to_3d"), (3, 7, "3_to_7d"), (7, None, "over_7d"))


def queue_depth() -> dict:
    """Open requests by status and urgency."""
    from django.db.models import Count

    from apps.customer_success.models import SupportRequest

    open_qs = SupportRequest.objects.filter(resolved_at__isnull=True)
    by_status = {
        row["status"]: row["n"]
        for row in open_qs.values("status").annotate(n=Count("id"))
    }
    by_urgency = {
        row["urgency"]: row["n"]
        for row in open_qs.values("urgency").annotate(n=Count("id"))
    }
    return {
        "open": open_qs.count(),
        "blocking": open_qs.filter(blocking=True).count(),
        "byStatus": by_status,
        "byUrgency": by_urgency,
    }


def sla_compliance(*, window_days: int = 30) -> dict:
    """
    First-response SLA compliance over a window.

    A request still open and already past its SLA counts as a BREACH, not as pending.
    Counting it as pending would let a permanently unanswered request never appear in the
    denominator — the compliance number would improve by ignoring the worst cases.
    """
    from apps.customer_success.models import SupportRequest

    since = timezone.now() - timezone.timedelta(days=window_days)
    qs = SupportRequest.objects.filter(created_at__gte=since)

    total = qs.count()
    if not total:
        return {"total": 0, "met": 0, "breached": 0, "rate": None, "windowDays": window_days}

    breached = 0
    met = 0
    now = timezone.now()
    for request in qs.only("first_response_at", "sla_due_at", "resolved_at").iterator():
        due = request.sla_due_at
        if due is None:
            continue
        responded = request.first_response_at
        if responded is not None:
            if responded <= due:
                met += 1
            else:
                breached += 1
        elif now > due:
            breached += 1  # still unanswered and already late

    measured = met + breached
    return {
        "total": total,
        "met": met,
        "breached": breached,
        "rate": round(met / measured, 3) if measured else None,
        "windowDays": window_days,
    }


def ageing() -> dict:
    """How long open requests have been waiting."""
    from apps.customer_success.models import SupportRequest

    now = timezone.now()
    buckets = {label: 0 for _lo, _hi, label in AGEING_BUCKETS}
    for request in SupportRequest.objects.filter(resolved_at__isnull=True).only("created_at"):
        age_days = (now - request.created_at).total_seconds() / 86400
        for low, high, label in AGEING_BUCKETS:
            if age_days >= low and (high is None or age_days < high):
                buckets[label] += 1
                break
    return buckets


def oldest_open(*, limit: int = 10) -> list[dict]:
    from apps.customer_success.models import SupportRequest

    return [
        {
            "id": str(r.id),
            "clientId": str(r.client_id),
            "subject": r.subject,
            "urgency": r.urgency,
            "blocking": r.blocking,
            "ownerName": r.owner_name,
            "openedAt": r.created_at.isoformat(),
            "slaDueAt": r.sla_due_at.isoformat() if r.sla_due_at else None,
        }
        for r in SupportRequest.objects.filter(resolved_at__isnull=True).order_by("created_at")[:limit]
    ]


def summary() -> dict:
    return {
        "queue": queue_depth(),
        "sla": sla_compliance(),
        "ageing": ageing(),
        "oldestOpen": oldest_open(),
    }
