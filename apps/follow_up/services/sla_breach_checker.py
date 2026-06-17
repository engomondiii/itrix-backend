"""
SLA breach checker.

Finds pending follow-up tasks whose effective due time has passed. Used by the scheduled
Celery beat job (and the overdue notifier) to surface breaches. Returns the overdue tasks
and, optionally, marks them so each breach is only notified once.
"""

from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

from apps.follow_up.models import FollowUpStatus, FollowUpTask


def find_overdue(*, now=None):
    """Return a queryset of pending tasks past their effective due time."""
    now = now or timezone.now()
    return FollowUpTask.objects.filter(status=FollowUpStatus.PENDING).filter(
        Q(snoozed_until__isnull=True, due_at__lt=now)
        | Q(snoozed_until__isnull=False, snoozed_until__lt=now)
    )


def find_unnotified_breaches(*, now=None):
    """Overdue tasks that haven't yet had a breach notification."""
    return find_overdue(now=now).filter(breach_notified=False)
