"""
Customer-success background tasks (Backend v6.0 §1.5).

    health recompute · digest build · SLA sweeps

The SLA sweep matters most: a support request that breaches its SLA silently is worse
than one that was never acknowledged, because the customer was told a time.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("itrix")

try:
    from tasks.celery import app
except Exception:  # noqa: BLE001
    app = None


def _task(func):
    if app is None:
        return func
    return app.task(name=f"itrix.customer_success.{func.__name__}")(func)


@_task
def recompute_health() -> dict:
    """Nightly health recompute across the book."""
    from apps.customer_success.services.health_calculator import recompute_all

    return recompute_all()


@_task
def sla_sweep() -> dict:
    """
    Find support requests past their SLA and alert.

    Only alerts ONCE per request — a breach that pages every five minutes gets muted,
    and a muted alert is the same as no alert.
    """
    from django.utils import timezone

    from apps.customer_success.models import SupportRequest

    breached = SupportRequest.objects.filter(
        resolved_at__isnull=True,
        sla_due_at__lt=timezone.now(),
        first_response_at__isnull=True,
    )
    count = 0
    for request in breached.iterator():
        try:
            from apps.notifications.services.notification_creator import notify_sla_breach

            notify_sla_breach(request)
        except Exception:  # noqa: BLE001
            logger.debug("SLA breach notification skipped")
        count += 1
    if count:
        logger.info("customer_success.sla_sweep %s breached request(s)", count)
    return {"breached": count}


@_task
def build_change_digests() -> dict:
    """Refresh the 'what changed' digest for active customers."""
    from apps.clients.models import Client
    from apps.customer_success.services import change_digest

    built = 0
    for client in Client.objects.filter(is_active=True).iterator():
        try:
            change_digest.build(client)
            built += 1
        except Exception:  # noqa: BLE001
            logger.exception("digest build failed for client %s", client.id)
    return {"built": built}


@_task
def regenerate_success_overviews() -> dict:
    """Rebuild the pinned State 10 overview on material change."""
    from apps.clients.models import Client
    from apps.journey.services import artifacts

    count = 0
    for client in Client.objects.filter(is_active=True).exclude(
        first_payment_recorded_at__isnull=True
    ).iterator():
        artifacts.regenerate_success_overview(client)
        count += 1
    return {"regenerated": count}
