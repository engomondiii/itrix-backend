"""
Celery tasks for notifications + SLA breach sweeps.

``check_sla_breaches`` is intended to run on a beat schedule; it notifies for any newly
overdue follow-up tasks. Eager when ENABLE_CELERY=False.
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger("itrix")


@shared_task(name="notifications.check_sla_breaches")
def check_sla_breaches_task() -> dict:
    from apps.follow_up.services.overdue_notifier import notify_overdue

    count = notify_overdue()
    return {"ok": True, "notified": count}


@shared_task(name="notifications.create")
def create_notification_task(kind: str, title: str, body: str = "", href: str = "") -> dict:
    from apps.notifications.services.notification_creator import create_notification

    n = create_notification(kind=kind, title=title, body=body, href=href)
    return {"ok": True, "notification_id": str(n.id)}
