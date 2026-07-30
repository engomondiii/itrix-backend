"""
The email-confirmation email.

── IT CONTAINS THE LINK AND NOTHING ELSE OF SUBSTANCE ──────────────────────
No organisation name, no workspace summary, no "you have 3 open support requests". An
email is forwarded, printed and left open on screens, and one that summarises an account is
a disclosure to whoever ends up holding it (Backend v7.2 §15.11).

It states the expiry, because an expiry the reader does not expect reads as a broken link
rather than as a security feature.
"""

from __future__ import annotations

from django.conf import settings

from apps.emails.models import EmailLog
from apps.emails.services.email_sender import send_email
from apps.emails.services.template_renderer import render

_SUBJECT = "Confirm your email address"
_BODY = (
    "Hi {{name}},\n\n"
    "Please confirm this is your address: {{link}}\n\n"
    "The link can be used once and expires in {{hours}} hours.\n\n"
    "You can use your workspace before confirming. Confirming lets us send you documents,"
    " and it is required before we can put an NDA in place.\n\n"
    "- itriX"
)


def build_verification_email(client, *, token: str) -> EmailLog:
    base = (getattr(settings, "FRONTEND_WEB_URL", "") or "").rstrip("/")
    hours = int(getattr(settings, "VERIFICATION_TOKEN_TTL_HOURS", 48))
    context = {
        "name": (getattr(client, "full_name", "") or "there"),
        "link": f"{base}/verify-email?token={token}",
        "hours": str(hours),
    }
    return send_email(
        kind=EmailLog.Kind.EMAIL_VERIFICATION,
        to_email=client.email,
        subject=_SUBJECT,
        body=render(_BODY, context),
        lead=getattr(client, "lead", None),
    )
