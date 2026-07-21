"""
Attachment background tasks (Backend v6.0 §1.5).

    scan · extract · excerpt · quarantine · NIGHTLY PURGE SWEEP

The purge sweep is a PRIVACY OBLIGATION, not a performance optimisation. It runs
correctly with ENABLE_CELERY off (CELERY_TASK_ALWAYS_EAGER makes ``.delay()`` inline), so
retention cannot quietly stop because a worker was never deployed.

── THE EXTRACTION QUEUE IS SEPARATE ─────────────────────────────────────────
``process_attachment`` is routed to the ``extraction`` queue so the sandbox worker can be
deployed with NO NETWORK EGRESS:

    celery -A tasks.celery worker -Q extraction --loglevel=info

A worker that also served the default queue would need egress for everything else, which
would defeat the isolation.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("itrix")

try:
    from tasks.celery import app
except Exception:  # noqa: BLE001
    app = None


def _task(func, **options):
    if app is None:
        return func
    return app.task(name=f"itrix.attachments.{func.__name__}", **options)(func)


def process_attachment(attachment_id: str) -> dict:
    """Scan, then extract, then build excerpts. Scan strictly precedes extraction."""
    from apps.attachments.models import Attachment
    from apps.attachments.services import intake

    attachment = Attachment.objects.filter(id=attachment_id).first()
    if attachment is None:
        return {"processed": False, "reason": "not found"}
    try:
        intake.process(attachment)
        attachment.refresh_from_db()
        return {"processed": True, "status": attachment.status}
    except Exception:  # noqa: BLE001
        logger.exception("attachment processing failed for %s", attachment_id)
        return {"processed": False, "reason": "error"}


def purge_sweep() -> dict:
    """Nightly retention purge. Verifiable."""
    from apps.attachments.services import retention

    return retention.sweep()


def rebuild_excerpts(attachment_id: str, query: str = "") -> int:
    """Re-select excerpts against a new query — relevance is per-turn, not per-file."""
    from apps.attachments.models import Attachment
    from apps.attachments.services import excerpts

    attachment = Attachment.objects.filter(id=attachment_id).first()
    if attachment is None:
        return 0
    return len(excerpts.build(attachment, query))


if app is not None:
    process_attachment = _task(process_attachment, queue="extraction")
    purge_sweep = _task(purge_sweep)
    rebuild_excerpts = _task(rebuild_excerpts, queue="extraction")


# ─────────────────────────────────────────────────────────────────────────────
# Celery beat schedule (Backend v6.0 §Phase 3)
# ─────────────────────────────────────────────────────────────────────────────
# Registered on the app at import so a deploy cannot forget to schedule them. Retention
# in particular is a PRIVACY OBLIGATION, not an optimisation — it must not quietly stop
# because somebody edited a settings file.
try:
    from celery.schedules import crontab

    BEAT_SCHEDULE = {
    "purge_sweep": {
        "task": "itrix.attachments.purge_sweep",
        "schedule": crontab(hour=4, minute=0),
    },  # nightly retention purge
    }

    if app is not None:
        existing = getattr(app.conf, "beat_schedule", None) or {}
        app.conf.beat_schedule = {**existing, **BEAT_SCHEDULE}
except Exception:  # noqa: BLE001 - celery optional
    BEAT_SCHEDULE = {}
