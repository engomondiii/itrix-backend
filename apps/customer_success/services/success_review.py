"""Success review scheduling and agenda assembly (Playbook §12 'Next review')."""

from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger("itrix")


def schedule(client, *, scheduled_at, agenda: list[str] | None = None):
    from apps.customer_success.models import SuccessReview

    return SuccessReview.objects.create(
        client=client, scheduled_at=scheduled_at, agenda=agenda or build_agenda(client)
    )


def build_agenda(client) -> list[str]:
    """
    Assemble the agenda from what is actually true right now.

    Ordered by what the CUSTOMER needs to discuss, not by what we want to sell. An
    off-plan outcome and a blocking issue both outrank anything commercial — and there
    is no commercial item in this list at all, by design.
    """
    from apps.customer_success.services import outcome_tracker, success_plan, support_router

    agenda: list[str] = []

    if support_router.open_blocking_for(client):
        agenda.append("Open blocking support issue and what we are doing about it")
    if outcome_tracker.any_off_plan(client):
        agenda.append("Outcomes that are off plan, and what would bring them back")

    pending = success_plan.pending_customer_actions(client)
    if pending.exists():
        agenda.append(f"{pending.count()} plan item(s) waiting on your side")

    agenda.append("Progress against the agreed outcomes")
    agenda.append("Anything you would like to change about how we work together")
    return agenda


def upcoming(client):
    from apps.customer_success.models import SuccessReview

    return (
        SuccessReview.objects.filter(client=client, completed_at__isnull=True,
                                     scheduled_at__gte=timezone.now())
        .order_by("scheduled_at")
        .first()
    )


def due_reviews(*, within_days: int = 7):
    """Reviews coming up — feeds the cockpit's success-review schedule."""
    from apps.customer_success.models import SuccessReview

    horizon = timezone.now() + timezone.timedelta(days=within_days)
    return SuccessReview.objects.filter(
        completed_at__isnull=True, scheduled_at__lte=horizon
    ).order_by("scheduled_at")
