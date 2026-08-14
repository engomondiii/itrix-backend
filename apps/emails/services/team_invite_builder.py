"""Email sent when a client invites a colleague from Workspace → Settings."""

from __future__ import annotations

from django.conf import settings

from apps.emails.models import EmailLog
from apps.emails.services.email_sender import send_email


def build_team_invite_email(client, *, invite_email: str) -> EmailLog:
    """Send the colleague invitation that the Settings screen promises was sent."""
    base = (getattr(settings, "FRONTEND_WEB_URL", "") or "").rstrip("/")
    sign_in = f"{base}/sign-in" if base else "/sign-in"
    sign_up = f"{base}/sign-up" if base else "/sign-up"
    inviter = client.full_name or client.email
    organisation = (client.organization or "").strip()
    from_line = f"{inviter} at {organisation}" if organisation else inviter

    body = (
        f"{from_line} invited you to collaborate in itriX.\n\n"
        "If you already have an itriX account, sign in here:\n"
        f"{sign_in}\n\n"
        "If you do not have an account yet, create one here:\n"
        f"{sign_up}\n\n"
        "Use this same email address when you sign in or create your account.\n\n"
        "— The itriX Assessment Team"
    )
    return send_email(
        kind=EmailLog.Kind.VISITOR,
        to_email=invite_email,
        subject=f"{inviter} invited you to itriX",
        body=body,
        lead=getattr(client, "lead", None),
    )
