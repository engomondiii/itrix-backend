"""
Celery application.

The app is named ``itrix`` and pulls its config from Django settings (the ``CELERY_``
namespaced keys in ``settings/base.py``). It autodiscovers task modules in this package.

Key behaviour: when ``ENABLE_CELERY=False`` (the default through Phase 2),
``CELERY_TASK_ALWAYS_EAGER`` is True, so ``.delay()`` / ``.apply_async()`` run the task
**synchronously, in-process** and return an EagerResult. That means every code path
that "queues" work still executes correctly with no broker/worker running — the whole
system is fully functional without Redis until you choose to turn Celery on.
"""

from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "itrix.settings.development")

app = Celery("itrix")

# Pull CELERY_* settings from Django config.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Discover tasks.py / *_tasks modules across installed apps and this package.
app.autodiscover_tasks()
for _related in (
    "ingestion_tasks",
    "ai_tasks",
    "scoring_tasks",
    "email_tasks",
    "analytics_tasks",
    "notification_tasks",
):
    app.autodiscover_tasks(["tasks"], related_name=_related)


# ── Scheduled jobs (Celery beat) ─────────────────────────────────────────────
# These run only when a beat process is active (ENABLE_CELERY=True + a worker/beat).
# With ENABLE_CELERY=False they simply never fire; the same work can be run manually.
app.conf.beat_schedule = {
    "check-sla-breaches-hourly": {
        "task": "notifications.check_sla_breaches",
        "schedule": 3600.0,  # every hour
    },
    "snapshot-metrics-daily": {
        "task": "analytics.snapshot_metrics",
        "schedule": 86400.0,  # every day
    },
}


@app.task(bind=True, ignore_result=True)
def debug_task(self):  # pragma: no cover
    print(f"Request: {self.request!r}")
