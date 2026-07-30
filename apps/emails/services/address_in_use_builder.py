"""
"Somebody tried to open a workspace with your address."

── IT GOES TO THE HOLDER, NEVER TO THE REQUESTER (§27.6) ───────────────────
This is the other half of the enumeration-safe registration response. The person who typed
the address learns nothing; the person who OWNS it is told that somebody tried, and how to
secure the account.

It names no requester and no organisation, and it contains NO LINK THAT SIGNS ANYONE IN —
a mail sent because an unauthenticated stranger typed an address must not carry a
credential.
"""

from __future__ import annotations

from django.conf import settings

from apps.emails.models import EmailLog
from apps.emails.services.email_sender import send_email
from apps.emails.services.template_renderer import render

_SUBJECT = "Someone tried to open an itriX workspace with your address"
_BODY = (
    "Hi {{name}},\n\n"
    "Somebody just tried to open an itriX workspace using this email address. If that was"
    " you, you already have one - sign in at {{signin}}, or reset your password at"
    " {{reset}} if you have forgotten it.\n\n"
    "If it was not you, no action is needed: nothing was created and nothing about your"
    " workspace has changed.\n\n"
    "- itriX"
)


def build_address_in_use_email(client) -> EmailLog:
    base = (getattr(settings, "FRONTEND_WEB_URL", "") or "").rstrip("/")
    context = {
        "name": (getattr(client, "full_name", "") or "there"),
        "signin": f"{base}/sign-in",
        "reset": f"{base}/forgot-password",
    }
    return send_email(
        kind=EmailLog.Kind.ADDRESS_IN_USE,
        to_email=client.email,
        subject=_SUBJECT,
        body=render(_BODY, context),
        lead=getattr(client, "lead", None),
    )
