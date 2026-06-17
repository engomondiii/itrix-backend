"""
Email utility.

A single, dependency-light entry point for sending mail that *always* respects the
``ENABLE_EMAIL_DELIVERY`` flag. In Phase 1 there is no ``emails`` app yet, so this
helper is what any code path uses to (optionally) notify someone. When the flag is
off — the Phase 1 default — it logs and no-ops, so the whole system runs without a
mail provider. Phase 3's ``emails`` app builds the richer templated layer on top.

The function never raises on delivery failure; it returns a bool so callers can
record an outcome without try/except noise.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger("itrix")


def send_email(
    *,
    subject: str,
    body: str,
    to: list[str] | str,
    from_email: str | None = None,
    html_body: str | None = None,
) -> bool:
    """
    Send a plain (and optionally HTML) email if delivery is enabled.

    Returns True if Django accepted the message for delivery, False if delivery is
    disabled or an error occurred. Never raises.
    """
    recipients = [to] if isinstance(to, str) else list(to)
    recipients = [r for r in recipients if r]
    if not recipients:
        logger.warning("send_email called with no recipients; skipping.")
        return False

    sender = from_email or settings.EMAIL_FROM

    if not settings.ENABLE_EMAIL_DELIVERY:
        logger.info(
            "[email-disabled] would send '%s' to %s (set ENABLE_EMAIL_DELIVERY=True to deliver)",
            subject,
            ", ".join(recipients),
        )
        return False

    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=sender,
            recipient_list=recipients,
            html_message=html_body,
            fail_silently=False,
        )
        logger.info("Sent email '%s' to %s", subject, ", ".join(recipients))
        return True
    except Exception:  # noqa: BLE001 - delivery must never break a request
        logger.exception("Failed to send email '%s'", subject)
        return False
