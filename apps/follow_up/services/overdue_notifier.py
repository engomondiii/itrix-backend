"""
Overdue notifier.

Creates an SLA-breach notification (and an optional alert) for each newly-overdue follow-up
task, marking the task so it isn't notified repeatedly. Invoked by the scheduled beat job.
"""

from __future__ import annotations

import logging

from apps.follow_up.services.sla_breach_checker import find_unnotified_breaches

logger = logging.getLogger("itrix")


def notify_overdue(*, now=None) -> int:
    """Notify for all unnotified breaches; return how many were notified."""
    from apps.notifications.services.notification_creator import notify_sla_breach

    count = 0
    for task in find_unnotified_breaches(now=now):
        notify_sla_breach(task)
        task.breach_notified = True
        task.save(update_fields=["breach_notified", "updated_at"])
        count += 1
    if count:
        logger.info("Notified %d overdue follow-up(s)", count)
    return count
