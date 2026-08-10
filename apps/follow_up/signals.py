"""
Lead operations fan-out.

Phase 3 wiring: when a Lead is created, fan out to the operations layer —

  * a follow-up SLA task (follow_up.task_creator),
  * an in-app notification (notifications.notification_creator),
  * an internal alert email (emails.internal_alert_builder),
  * a visitor confirmation email when we have their address (emails.confirmation_email_builder).

This is implemented as a ``post_save`` signal on ``leads.Lead`` so Phase 2's LeadCreator
stays untouched and the fan-out is purely additive. Each step is wrapped defensively: an
operations failure must never break lead creation / the public funnel. All side effects are
flag-aware (emails stub out when delivery is disabled; tasks run inline when Celery is off).

The handler is connected from ``FollowUpConfig.ready()``.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger("itrix")


@receiver(post_save, sender="leads.Lead", dispatch_uid="leads_operations_fanout")
def on_lead_saved(sender, instance, created, **kwargs):
    if not created:
        return

    lead = instance

    # 1) Follow-up SLA task
    try:
        from apps.follow_up.services.task_creator import create_followup_for_lead

        create_followup_for_lead(lead)
    except Exception:  # noqa: BLE001
        logger.exception("Fan-out: follow-up task creation failed for lead %s", lead.id)

    # 2) In-app notification
    try:
        from apps.notifications.services.notification_creator import notify_new_lead

        notify_new_lead(lead)
    except Exception:  # noqa: BLE001
        logger.exception("Fan-out: notification creation failed for lead %s", lead.id)

    # 3) Internal alert email (stubbed unless delivery enabled)
    # ── CELERY OFFLOAD (2026-08-10) ──────────────────────────────────────────
    # Steps 3 and 4 are SMTP round-trips, and this signal fires inside the request
    # that created the lead (qualification submit, open signup) — with real delivery
    # on, that is up to two synchronous mailbox calls on the visitor's critical
    # path. The `emails.*` tasks were written for exactly this hand-off ("wrappers
    # so email sends can be offloaded... the lead fan-out works with or without a
    # worker") and were never wired. With ENABLE_CELERY on, the sends are enqueued
    # ON COMMIT — the tasks re-fetch the lead by id, so the worker must not race a
    # transaction that could still roll the row back. With it off, behaviour is
    # byte-for-byte the old inline send.
    use_celery = getattr(settings, "ENABLE_CELERY", False)
    try:
        if use_celery:
            from tasks.email_tasks import send_internal_alert_task

            transaction.on_commit(lambda: send_internal_alert_task.delay(str(lead.id)))
        else:
            from apps.emails.services.internal_alert_builder import build_internal_alert

            build_internal_alert(lead)
    except Exception:  # noqa: BLE001
        logger.exception("Fan-out: internal alert failed for lead %s", lead.id)

    # 4) Visitor confirmation (only if we already have an email)
    try:
        if lead.email:
            if use_celery:
                from tasks.email_tasks import send_confirmation_task

                transaction.on_commit(lambda: send_confirmation_task.delay(str(lead.id)))
            else:
                from apps.emails.services.confirmation_email_builder import build_confirmation_email

                build_confirmation_email(lead)
    except Exception:  # noqa: BLE001
        logger.exception("Fan-out: confirmation email failed for lead %s", lead.id)
