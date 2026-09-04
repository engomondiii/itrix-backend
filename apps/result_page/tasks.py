"""Background My Review generation task.

READY is written only after complete schema validation. After bounded retries a failure is
persisted as FAILED so the UI can offer a real retry instead of displaying partial content.
"""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger("itrix")
RETRY_BACKOFF_BASE = 30


@shared_task(name="result_page.generate", bind=True, max_retries=2, acks_late=True)
def generate_result_page_task(self, lead_id: str, finalize_conversation: bool = False) -> dict:
    from django.db import close_old_connections

    close_old_connections()
    try:
        from apps.leads.models import Lead
        from apps.result_page.services.result_generator import ResultGenerator

        lead = Lead.objects.filter(pk=lead_id).first()
        if lead is None:
            logger.warning("result_page.generate: no lead %s", lead_id)
            return {"ok": False, "error": "not_found"}
        page, report = ResultGenerator().generate_for_lead(lead)
        if finalize_conversation:
            from apps.conversations.services.reveal_bridge import finalize_ready_review

            finalize_ready_review(lead)
        return {
            "ok": True,
            "lead_id": lead_id,
            "result_page_id": str(page.id),
            "status": page.generation_status,
            "used_ai": bool(report.get("used_ai", False)),
            "chunk_count": int(report.get("chunk_count", 0)),
        }
    except Exception as exc:  # noqa: BLE001
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=RETRY_BACKOFF_BASE * (2**self.request.retries))
        logger.exception("result_page.generate: giving up for lead %s", lead_id)
        try:
            from apps.leads.models import Lead
            from apps.result_page.services.result_generator import ResultGenerator

            lead = Lead.objects.filter(pk=lead_id).first()
            if lead is not None:
                ResultGenerator.mark_failed(lead, exc)
        except Exception:  # noqa: BLE001
            logger.exception("result_page.generate: could not persist FAILED state")
        return {"ok": False, "lead_id": lead_id, "status": "failed", "error": "generation_failed"}
    finally:
        close_old_connections()
