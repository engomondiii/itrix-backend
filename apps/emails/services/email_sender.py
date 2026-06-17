"""
Email sender.

The single choke-point for outbound email. It always writes an ``EmailLog`` row, then:

* if ``ENABLE_EMAIL_DELIVERY`` is False (default) → marks the log ``stubbed`` and returns
  without contacting any provider (the whole flow works with no API key);
* if enabled → sends via Resend (imported lazily) and records ``sent`` / ``failed``.

Callers (the builders) hand it a fully-rendered subject + body.
"""

from __future__ import annotations

import logging

from django.conf import settings

from apps.emails.models import EmailLog

logger = logging.getLogger("itrix")


def send_email(
    *,
    kind: str,
    to_email: str,
    subject: str,
    body: str,
    lead=None,
    from_email: str | None = None,
) -> EmailLog:
    """Build + (optionally) send an email, always returning the EmailLog record."""
    sender = from_email or getattr(settings, "EMAIL_FROM", "") or "team@itrix.example"

    log = EmailLog.objects.create(
        kind=kind,
        to_email=to_email,
        from_email=sender,
        subject=subject,
        body=body,
        lead=lead,
        status=EmailLog.Status.STUBBED,
    )

    if not getattr(settings, "ENABLE_EMAIL_DELIVERY", False):
        logger.info("[email-stubbed] %s -> %s | %s", kind, to_email, subject)
        return log

    if not to_email:
        log.status = EmailLog.Status.FAILED
        log.error = "No recipient address."
        log.save(update_fields=["status", "error", "updated_at"])
        return log

    try:
        import resend  # noqa: PLC0415 - lazy

        resend.api_key = settings.RESEND_API_KEY
        from_name = getattr(settings, "EMAIL_FROM_NAME", "") or "iTrix"
        result = resend.Emails.send(
            {
                "from": f"{from_name} <{sender}>",
                "to": [to_email],
                "subject": subject,
                "text": body,
            }
        )
        log.status = EmailLog.Status.SENT
        log.provider_message_id = (result or {}).get("id", "") if isinstance(result, dict) else ""
        log.save(update_fields=["status", "provider_message_id", "updated_at"])
        logger.info("Email sent %s -> %s", kind, to_email)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Email send failed")
        log.status = EmailLog.Status.FAILED
        log.error = str(exc)[:2000]
        log.save(update_fields=["status", "error", "updated_at"])
    return log
