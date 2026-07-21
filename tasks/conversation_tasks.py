"""
Conversation background tasks (Backend v6.0 §1.5).

    rolling_summaries       compress CLOSED states so long threads stay answerable
    thread_titling          title a thread from its first exchange
    anon_retention_sweep    purge anonymous threads whose window has closed

All three are Celery tasks that also run correctly SYNCHRONOUSLY: with ENABLE_CELERY off,
``CELERY_TASK_ALWAYS_EAGER`` is true and calling ``.delay()`` executes inline. So none of
this depends on a broker being present — which matters because the retention sweep is a
PRIVACY obligation, not a performance optimisation, and must not quietly stop running
because a worker was not deployed.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("itrix")

try:
    from tasks.celery import app
except Exception:  # noqa: BLE001 - celery optional
    app = None


def _task(func):
    """Register with Celery when available; otherwise leave the plain callable."""
    if app is None:
        return func
    return app.task(name=f"itrix.conversations.{func.__name__}")(func)


@_task
def anon_retention_sweep() -> int:
    """
    Purge anonymous threads whose retention window has closed.

    A visitor who never creates an account keeps their threads for the anonymous-session
    retention window AND NO LONGER (Architecture v2.6 §10.3). This is the job that makes
    that sentence true rather than aspirational.

    Returns the number purged.
    """
    from apps.conversations.services.threads import purge_expired_anonymous_threads

    try:
        count = purge_expired_anonymous_threads()
        logger.info("anon_retention_sweep purged %s thread(s)", count)
        return count
    except Exception:  # noqa: BLE001
        logger.exception("anon_retention_sweep failed")
        return 0


@_task
def thread_titling(thread_id: str) -> str:
    """
    Title a thread from its first exchange, then freeze it.

    Deterministic in Phase 1 (the visitor's own words). The low-temperature generated
    title arrives in Phase 2 bound to Claim-Card level 1 — a title is visitor-visible, so
    it inherits the no-inference rule and may never name an inferred organisation.
    """
    from apps.conversations.models import Message, Thread
    from apps.conversations.services import threads as thread_svc

    thread = Thread.objects.filter(id=thread_id).first()
    if thread is None:
        return ""
    first = (
        Message.objects.filter(thread=thread, sender_kind__in=["visitor", "client"])
        .order_by("seq", "created_at")
        .first()
    )
    if first is None:
        return thread.title or ""
    thread_svc.set_title_if_unset(thread, first.body or "")
    return thread.title


@_task
def rolling_summaries(thread_id: str, state_key: str = "") -> str:
    """
    Build and persist the rolling summary for a thread's CLOSED states.

    RULE 2 (§2.4): the visitor's own words are NEVER summarized away within the CURRENT
    state. This task therefore only ever runs against states the subject has already
    left — the thing they just told us is the one thing we must not compress.
    """
    from apps.conversations.models import Thread
    from apps.conversations.services.context_assembly import summarize_thread_state

    thread = Thread.objects.filter(id=thread_id).first()
    if thread is None:
        return ""
    try:
        return summarize_thread_state(thread, state_key)
    except Exception:  # noqa: BLE001
        logger.exception("rolling_summaries failed for thread %s", thread_id)
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# Celery beat schedule (Backend v6.0 §Phase 3)
# ─────────────────────────────────────────────────────────────────────────────
# Registered on the app at import so a deploy cannot forget to schedule them. Retention
# in particular is a PRIVACY OBLIGATION, not an optimisation — it must not quietly stop
# because somebody edited a settings file.
try:
    from celery.schedules import crontab

    BEAT_SCHEDULE = {
    "anon_retention_sweep": {
        "task": "itrix.conversations.anon_retention_sweep",
        "schedule": crontab(hour=4, minute=30),
    },  # anonymous thread expiry
    }

    if app is not None:
        existing = getattr(app.conf, "beat_schedule", None) or {}
        app.conf.beat_schedule = {**existing, **BEAT_SCHEDULE}
except Exception:  # noqa: BLE001 - celery optional
    BEAT_SCHEDULE = {}
