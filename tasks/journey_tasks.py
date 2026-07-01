"""
Celery tasks for journey lifecycle maintenance.

  * ``journey_sla_nudge``     — flag leads that have sat in a state past their SLA.
  * ``sweep_dormant``         — move stale CLIENT_PAGE/INVITED leads to DORMANT.
  * ``expire_invites``        — housekeeping for expired single-use invites.

All are safe no-ops when there's nothing to do, and eager when ENABLE_CELERY is False.
They never mutate journey state directly — they go through ``journey.advance``.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger("itrix")

# How long a lead may sit in a pre-conversion state before we sweep it to DORMANT.
_DORMANT_AFTER_DAYS = 30


@shared_task(name="journey.sla_nudge")
def journey_sla_nudge_task() -> dict:
    """Log leads sitting in DIAGNOSED/CLIENT_PAGE past their SLA (nudge hook)."""
    from apps.journey.models import JourneyState
    from apps.leads.models import Lead

    overdue = Lead.objects.filter(
        journey_state__in=[JourneyState.DIAGNOSED, JourneyState.CLIENT_PAGE],
        sla_response_due_at__lt=timezone.now(),
        first_response_at__isnull=True,
    )
    count = overdue.count()
    if count:
        logger.info("journey SLA nudge: %s lead(s) past due", count)
    return {"ok": True, "nudged": count}


@shared_task(name="journey.sweep_dormant")
def sweep_dormant_task() -> dict:
    """Move stale CLIENT_PAGE / INVITED leads to DORMANT via journey.advance."""
    from apps.journey.models import JourneyEvent, JourneyState
    from apps.journey.services.advance import advance
    from apps.leads.models import Lead

    cutoff = timezone.now() - timedelta(days=_DORMANT_AFTER_DAYS)
    stale = Lead.objects.filter(
        journey_state__in=[JourneyState.CLIENT_PAGE, JourneyState.INVITED],
        updated_at__lt=cutoff,
    )
    swept = 0
    for lead in stale.iterator():
        try:
            advance(lead, JourneyEvent.GATE_DORMANT, meta={"reason": "sweep_dormant"})
            swept += 1
        except Exception:  # noqa: BLE001
            logger.exception("sweep_dormant failed for lead %s", lead.id)
    if swept:
        logger.info("journey sweep_dormant: %s lead(s) → DORMANT", swept)
    return {"ok": True, "swept": swept}


@shared_task(name="journey.expire_invites")
def expire_invites_task() -> dict:
    """
    Housekeeping for expired invites. Consumed-invite nonces older than the invite TTL
    are pruned (they can never be reused anyway; this just keeps the ledger tidy).
    """
    from django.conf import settings

    from apps.clients.models_consumed import ConsumedInvite

    ttl_hours = int(getattr(settings, "ACCOUNT_INVITE_TTL_HOURS", 72))
    cutoff = timezone.now() - timedelta(hours=ttl_hours * 2)
    stale = ConsumedInvite.objects.filter(created_at__lt=cutoff)
    pruned = stale.count()
    stale.delete()
    if pruned:
        logger.info("journey expire_invites: pruned %s consumed-invite record(s)", pruned)
    return {"ok": True, "pruned": pruned}
