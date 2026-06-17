"""
Celery tasks for AI result generation.

Wrapper around the result generator so result generation can be offloaded. Eager when
``ENABLE_CELERY`` is False.
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger("itrix")


@shared_task(name="ai.generate_result_for_lead")
def generate_result_for_lead_task(lead_id: str) -> dict:
    from apps.leads.models import Lead
    from apps.result_page.services.result_generator import ResultGenerator

    lead = Lead.objects.filter(pk=lead_id).first()
    if not lead:
        return {"ok": False, "error": f"No lead {lead_id}"}
    result_obj, report = ResultGenerator().generate_for_lead(lead)
    return {"ok": True, "lead_id": str(lead.id), "result_page_id": str(result_obj.id), **report}
