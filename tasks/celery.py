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
# Every *_tasks module in this package, explicitly. This list previously named only six
# of the twelve modules, so tasks defined in the other six (agent/artifact/attachment/
# conversation/customer_success/journey) were never imported by a `celery worker` boot —
# any message enqueued for them would have arrived as "Received unregistered task".
# Harmless while ENABLE_CELERY was False (eager mode imports at the call site); a real
# worker deployment needs the full inventory registered before it consumes.
for _related in (
    "agent_tasks",
    "ai_tasks",
    "analytics_tasks",
    "artifact_tasks",
    "attachment_tasks",
    "conversation_tasks",
    "customer_success_tasks",
    "email_tasks",
    "ingestion_tasks",
    "journey_tasks",
    "notification_tasks",
    "scoring_tasks",
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
