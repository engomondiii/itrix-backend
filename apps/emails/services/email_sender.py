"""
Email sender.

The single choke-point for outbound email. It always writes an ``EmailLog`` row, then:

* if ``ENABLE_EMAIL_DELIVERY`` is False → marks the log ``stubbed`` and returns without
  contacting any provider (the whole flow works with no credentials at all);
* if enabled → delivers through the configured provider and records ``sent`` / ``failed``.

Callers (the builders) hand it a fully-rendered subject + body.

── TWO PROVIDERS, AND WHY THE CHOICE LIVES IN SETTINGS ─────────────────────
``settings.EMAIL_PROVIDER`` is resolved once, at boot, in ``itrix/settings/base.py``:

    smtp    Django's mail backend — Gmail / Google Workspace, or any SMTP host
    resend  the Resend HTTP API
    none    nothing is configured; a send is logged as failed with that reason

Resolving it in settings rather than here means the answer to "how does this deployment
send mail" is a single value you can print, not a chain of ``if`` statements spread across
a service. This function only dispatches.

── WHY A REFUSAL IS STILL A LOG ROW ────────────────────────────────────────
Every path through this function writes an ``EmailLog``, including the confirmation gate
and the "no provider configured" branch. A refusal that left no trace would be
indistinguishable from a mail that was never attempted, and the difference between those
two is the whole of a support conversation.
"""

from __future__ import annotations

import logging

from django.conf import settings

from apps.emails.models import EmailLog

logger = logging.getLogger("itrix")


def _sender_address() -> str:
    """The bare address mail is sent from."""
    return getattr(settings, "EMAIL_FROM", "") or "team@itrix.example"


def _sender_header() -> str:
    """
    The From header, with a display name when one is configured.

    Gmail rewrites — or refuses — a From address that is neither the authenticated
    mailbox nor a verified alias of it. ``settings.EMAIL_FROM`` already defaults to
    ``EMAIL_HOST_USER`` for the SMTP provider precisely so this header is acceptable
    without anybody having to remember to set a second variable.
    """
    address = _sender_address()
    name = getattr(settings, "EMAIL_FROM_NAME", "") or ""
    return f"{name} <{address}>" if name else address


def _log(
    *,
    kind: str,
    to_email: str,
    subject: str,
    body: str,
    lead,
    cc,
    attachments,
    scheduled_at,
    status: str,
    error: str = "",
) -> EmailLog:
    return EmailLog.objects.create(
        kind=kind,
        to_email=to_email,
        from_email=_sender_address(),
        subject=subject,
        body=body,
        lead=lead,
        cc=cc or [],
        attachments=attachments or [],
        scheduled_at=scheduled_at,
        status=status,
        error=error,
    )


def _deliver_smtp(*, to_email: str, subject: str, body: str, cc) -> str:
    """
    Send through Django's mail backend. Returns a provider message id (empty for SMTP).

    Raises on failure — the caller records it. ``fail_silently`` is deliberately NOT used:
    a silent failure here would be written to the log as ``sent``, which is worse than the
    error it hides.
    """
    from django.core.mail import EmailMultiAlternatives  # noqa: PLC0415 - lazy

    from apps.emails.services.html_body import html_from_text  # noqa: PLC0415 - lazy

    message = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=_sender_header(),
        to=[to_email],
        cc=list(cc or []) or None,
    )
    # ── CLICKABLE LINKS (fix, 2026-08-12) ────────────────────────────────────
    # Text-only mail left the confirmation link as dead text in clients that do not
    # auto-detect URLs — and a confirmation link nobody can click is a workspace
    # nobody can finish opening. The plain text stays the canonical body and the
    # first part of the message; the HTML is generated from it, so there is no second
    # copy of the wording to drift.
    message.attach_alternative(html_from_text(body), "text/html")
    sent_count = message.send(fail_silently=False)
    if not sent_count:
        # The backend accepted the call and delivered nothing. Treated as a failure
        # rather than logged as sent, because "sent" is a claim we would be quoting
        # back to somebody who never received it.
        raise RuntimeError("SMTP backend accepted the message but reported 0 sent.")
    return ""


def _deliver_resend(*, to_email: str, subject: str, body: str) -> str:
    """Send through the Resend HTTP API. Returns the provider message id."""
    import resend  # noqa: PLC0415 - lazy

    resend.api_key = settings.RESEND_API_KEY
    from apps.emails.services.html_body import html_from_text  # noqa: PLC0415 - lazy

    result = resend.Emails.send(
        {
            "from": _sender_header(),
            "to": [to_email],
            "subject": subject,
            # Both parts, for the same reason as the SMTP path. A provider given only
            # `text` cannot produce a clickable link in a client that does not
            # auto-detect one.
            "text": body,
            "html": html_from_text(body),
        }
    )
    return (result or {}).get("id", "") if isinstance(result, dict) else ""


def send_email(
    *,
    kind: str,
    to_email: str,
    subject: str,
    body: str,
    lead=None,
    from_email: str | None = None,
    cc=None,
    attachments=None,
    scheduled_at=None,
) -> EmailLog:
    """Build + (optionally) send an email, always returning the EmailLog record."""
    # `from_email` is accepted for signature compatibility with every existing caller.
    # It is recorded but does not override the envelope sender: with SMTP the sender has
    # to be the authenticated mailbox, and a per-call override is exactly how a caller
    # would produce a message the provider then rejects.
    if from_email and from_email != _sender_address():
        logger.info("email.sender_override_ignored")

    common = {
        "kind": kind,
        "to_email": to_email,
        "subject": subject,
        "body": body,
        "lead": lead,
        "cc": cc,
        "attachments": attachments,
        "scheduled_at": scheduled_at,
    }

    # ── v7.2 — CONFIRMATION GATE, AT THE ONLY CHOKE-POINT (R66 item 1) ──────
    # No non-transactional email goes to an address that belongs to an unconfirmed
    # workspace. It is enforced HERE rather than in each builder because this function is
    # documented as "the single choke-point for outbound email" — and a rule placed
    # anywhere else is a rule every future builder has to remember.
    try:
        from apps.clients.services.verification import may_send

        allowed, reason = may_send(kind, to_email)
    except Exception:  # noqa: BLE001 - the gate must never take out the mail path
        allowed, reason = True, ""
    if not allowed:
        logger.info("email.blocked_unconfirmed kind=%s", kind)
        return _log(**common, status=EmailLog.Status.FAILED, error=reason)

    log = _log(**common, status=EmailLog.Status.STUBBED)

    # A future-dated send is queued, never delivered inline.
    if scheduled_at is not None:
        logger.info("email.scheduled kind=%s at=%s", kind, scheduled_at)
        return log

    if not getattr(settings, "ENABLE_EMAIL_DELIVERY", False):
        logger.info("email.stubbed kind=%s", kind)
        return log

    if not to_email:
        log.status = EmailLog.Status.FAILED
        log.error = "No recipient address."
        log.save(update_fields=["status", "error", "updated_at"])
        return log

    provider = (getattr(settings, "EMAIL_PROVIDER", "none") or "none").lower()

    if provider == "none":
        # Delivery is switched ON but nothing is configured to deliver with. Recorded as a
        # failure with the fix in the message, because the alternative is a stubbed row
        # that looks identical to a deployment which intended not to send.
        log.status = EmailLog.Status.FAILED
        log.error = (
            "ENABLE_EMAIL_DELIVERY is on but no provider is configured. Set "
            "EMAIL_HOST_USER + EMAIL_HOST_PASSWORD for SMTP, or RESEND_API_KEY."
        )
        log.save(update_fields=["status", "error", "updated_at"])
        logger.error("email.no_provider kind=%s", kind)
        return log

    try:
        if provider == "smtp":
            message_id = _deliver_smtp(to_email=to_email, subject=subject, body=body, cc=cc)
        else:
            message_id = _deliver_resend(to_email=to_email, subject=subject, body=body)
        log.status = EmailLog.Status.SENT
        log.provider_message_id = message_id or ""
        log.save(update_fields=["status", "provider_message_id", "updated_at"])
        logger.info("email.sent provider=%s kind=%s", provider, kind)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Email send failed (%s)", provider)
        log.status = EmailLog.Status.FAILED
        log.error = str(exc)[:2000]
        log.save(update_fields=["status", "error", "updated_at"])
    return log
