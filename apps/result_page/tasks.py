"""
Celery task for background result-page generation — the "Celery-preferred" path.

``apps.review.services.qualification_processor._kick_off_result_page`` imports
``generate_result_page_task`` from THIS module when ``ENABLE_CELERY`` is on. Until this
module existed, that import raised, the exception was swallowed, and the processor fell
back to its daemon-thread path on every qualification — the Celery branch was dead code.
Creating this module is what makes the durable path real: the qualify request enqueues,
returns the capability token immediately, and a worker builds the AI-enriched page.

Placed in ``apps/result_page/`` (not ``tasks/``) because the import site names this exact
path, and ``app.autodiscover_tasks()`` in ``tasks/celery.py`` already scans every
installed app for a ``tasks`` module — no registration change is needed anywhere.

── WHY THE TASK NEVER RAISES TO THE CALLER ──────────────────────────────────
Same contract as the thread path it replaces (``_build_result_page_now``): result-page
enrichment is best-effort and the ``/c/[token]`` page regenerates a deterministic page on
demand if the background build hasn't landed. So nothing user-visible may ever depend on
this task succeeding. Transient failures (broker hiccup already can't reach here; think
DB restart, model-API timeout) get a SHORT bounded retry; after that we log loudly and
return a failure dict — the house convention (see ``tasks/email_tasks.py``), which keeps
the worker log as the single place operators look.

── EAGER-SAFE ───────────────────────────────────────────────────────────────
With ``ENABLE_CELERY=False`` the qualification processor never imports this task (it uses
the thread), but tests and shells may still call ``.delay()`` directly; eager mode runs it
inline, including inline retries, so behaviour is identical with or without a worker.
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger("itrix")

#: Base delay for the bounded retry (seconds); attempt N waits RETRY_BACKOFF_BASE * 2^N.
RETRY_BACKOFF_BASE = 30


@shared_task(
    name="result_page.generate",
    bind=True,
    max_retries=2,
    # Late-ack so a worker killed mid-build (deploy, OOM) returns the job to the queue
    # instead of losing it. Safe because generate_for_lead() is idempotent — it persists
    # by lead and the enriched page simply replaces the deterministic one.
    acks_late=True,
)
def generate_result_page_task(self, lead_id: str) -> dict:
    """Build + persist the personalized result page for ``lead_id`` off the request path."""
    from django.db import close_old_connections

    # Long-lived worker process: drop any connection the pool thinks is alive but the
    # server has closed, exactly as the thread path did before us.
    close_old_connections()
    try:
        from apps.leads.models import Lead
        from apps.result_page.services.result_generator import ResultGenerator

        lead = Lead.objects.filter(pk=lead_id).first()
        if lead is None:
            # Purged or bogus id: nothing to build, and retrying cannot help.
            logger.warning("result_page.generate: no lead %s (skipping)", lead_id)
            return {"ok": False, "error": f"No lead {lead_id}"}

        page, report = ResultGenerator().generate_for_lead(lead)
        return {
            "ok": True,
            "lead_id": lead_id,
            "result_page_id": str(page.id),
            "used_ai": bool(report.get("used_ai", False)),
            "chunk_count": int(report.get("chunk_count", 0)),
        }
    except Exception as exc:  # noqa: BLE001 - bounded retry, then log-and-return
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=RETRY_BACKOFF_BASE * (2**self.request.retries))
        logger.exception(
            "result_page.generate: giving up for lead %s after %d attempts",
            lead_id,
            self.request.retries + 1,
        )
        return {"ok": False, "lead_id": lead_id, "error": str(exc)}
    finally:
        close_old_connections()
