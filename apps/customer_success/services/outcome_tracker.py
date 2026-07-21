"""
Outcome tracking (Playbook §12B).

These are the CUSTOMER's outcomes. The module has no concept of a sales target, a
pipeline stage or a commercial probability, and adding one would be a defect rather
than a feature.

The four status words are used EXACTLY as written: On plan · At risk · Off plan ·
Achieved. ``set_status`` refuses anything else, which is what stops "Off plan" from
drifting into "progressing" one well-meaning edit at a time.
"""

from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger("itrix")


def create(client, *, title: str, measure: str = "", owner_side: str = "shared",
           owner_name: str = "", target_date=None, description: str = ""):
    from apps.customer_success.models import Outcome

    return Outcome.objects.create(
        client=client,
        title=title[:300],
        description=description,
        measure=measure[:300],
        owner_side=owner_side,
        owner_name=owner_name[:200],
        target_date=target_date,
    )


def set_status(outcome, status: str, *, note: str = ""):
    """
    Change an outcome's status.

    Rejects anything outside the four approved words. A status field that accepts free
    text becomes a place to hide bad news.
    """
    from apps.customer_success.models import OutcomeStatus

    valid = {choice[0] for choice in OutcomeStatus.choices}
    if status not in valid:
        raise ValueError(f"Unknown outcome status {status!r}. Allowed: {sorted(valid)}")

    outcome.status = status
    fields = ["status", "updated_at"]
    if note:
        outcome.status_note = note
        fields.append("status_note")
    if status == OutcomeStatus.ACHIEVED and outcome.achieved_at is None:
        outcome.achieved_at = timezone.now()
        fields.append("achieved_at")
    outcome.save(update_fields=fields)

    try:
        from apps.customer_success.services.health_calculator import recompute

        recompute(outcome.client)
    except Exception:  # noqa: BLE001
        pass
    return outcome


def for_client(client):
    from apps.customer_success.models import Outcome

    return Outcome.objects.filter(client=client).order_by("target_date", "-created_at")


def any_off_plan(client) -> bool:
    """Read by the customer-first NBA rule."""
    from apps.customer_success.models import Outcome, OutcomeStatus

    if client is None:
        return False
    return Outcome.objects.filter(
        client=client, status__in=[OutcomeStatus.OFF_PLAN, OutcomeStatus.AT_RISK]
    ).exists()


def distribution(client) -> dict:
    """Status counts for the customer's own view — never a percentage complete."""
    from django.db.models import Count

    from apps.customer_success.models import Outcome, OutcomeStatus

    rows = (
        Outcome.objects.filter(client=client)
        .values("status")
        .annotate(n=Count("id"))
    )
    counts = {row["status"]: row["n"] for row in rows}
    return {choice[0]: counts.get(choice[0], 0) for choice in OutcomeStatus.choices}
