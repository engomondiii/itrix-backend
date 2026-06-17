"""
Celery tasks for email.

Wrappers so email sends can be offloaded. Eager when ENABLE_CELERY=False (runs inline), so
the lead fan-out works with or without a worker.
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger("itrix")


@shared_task(name="emails.send_confirmation")
def send_confirmation_task(lead_id: str) -> dict:
    from apps.emails.services.confirmation_email_builder import build_confirmation_email
    from apps.leads.models import Lead

    lead = Lead.objects.filter(pk=lead_id).first()
    if not lead:
        return {"ok": False, "error": f"No lead {lead_id}"}
    log = build_confirmation_email(lead)
    return {"ok": True, "status": log.status, "email_log_id": str(log.id)}


@shared_task(name="emails.send_internal_alert")
def send_internal_alert_task(lead_id: str) -> dict:
    from apps.emails.services.internal_alert_builder import build_internal_alert
    from apps.leads.models import Lead

    lead = Lead.objects.filter(pk=lead_id).first()
    if not lead:
        return {"ok": False, "error": f"No lead {lead_id}"}
    log = build_internal_alert(lead)
    return {"ok": True, "status": log.status, "email_log_id": str(log.id)}


@shared_task(name="emails.send_follow_up")
def send_follow_up_task(lead_id: str) -> dict:
    from apps.emails.services.follow_up_email_builder import build_follow_up_email
    from apps.leads.models import Lead

    lead = Lead.objects.filter(pk=lead_id).first()
    if not lead:
        return {"ok": False, "error": f"No lead {lead_id}"}
    log = build_follow_up_email(lead)
    return {"ok": True, "status": log.status, "email_log_id": str(log.id)}
