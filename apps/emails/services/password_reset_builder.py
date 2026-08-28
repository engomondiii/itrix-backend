"""
The password-reset email.

Same rule as the confirmation email: the link, the expiry, and nothing else of substance.
It does not name the organisation and does not summarise the workspace.
"""

from __future__ import annotations

from django.conf import settings

from apps.emails.models import EmailLog
from apps.emails.services.email_sender import send_email
from apps.emails.services.template_renderer import render

_SUBJECT = "Reset your itriX password"
_BODY = (
    "Hi {{name}},\n\n"
    "You can set a new password here: {{link}}\n\n"
    "The link can be used once and expires in {{minutes}} minutes. Requesting another one"
    " invalidates this link.\n\n"
    "If you did not ask for this, nothing has changed and you can ignore this message.\n\n"
    "- itriX"
)


def build_password_reset_email(client, *, token: str) -> EmailLog:
    base = (getattr(settings, "FRONTEND_WEB_URL", "") or "").rstrip("/")
    minutes = int(getattr(settings, "RESET_TOKEN_TTL_MINUTES", 60))
    context = {
        "name": (getattr(client, "full_name", "") or "there"),
        "link": f"{base}/reset-password?token={token}",
        "minutes": str(minutes),
    }
    return send_email(
        kind=EmailLog.Kind.PASSWORD_RESET,
        to_email=client.email,
        subject=_SUBJECT,
        body=render(_BODY, context),
        lead=getattr(client, "lead", None),
        delivery_attempts=int(getattr(settings, "PASSWORD_RESET_EMAIL_ATTEMPTS", 2)),
    )
