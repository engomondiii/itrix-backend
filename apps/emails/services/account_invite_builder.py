"""
Account-invite email builder (reveal ②).

When a lead passes the invite gate, this emails them a single-use invite link to create
their portal account (reveal ②→③). Value has already been delivered (the client page),
so this is a value-first, earned ask. Delivery is gated by ENABLE_EMAIL_DELIVERY.

The link carries the single-use account_invite capability token minted by the journey
reveal / invite service.
"""

from __future__ import annotations

from django.conf import settings

from apps.emails.models import EmailLog
from apps.emails.services.email_sender import send_email
from apps.emails.services.template_renderer import render

_SUBJECT = "Your iTrix private workspace is ready"
_BODY = (
    "Hi {{name}},\n\n"
    "Based on your review, we'd like to invite you into a private workspace where we can go"
    " deeper — share materials, run an evaluation, and talk directly with our team.\n\n"
    "Set up your account here (this link is single-use): {{link}}\n\n"
    "There's no obligation; the workspace simply lets us collaborate securely.\n\n"
    "— The iTrix Assessment Team"
)


def build_account_invite_email(lead, *, invite_token: str) -> EmailLog:
    base = getattr(settings, "FRONTEND_WEB_URL", "") or ""
    link = f"{base}/invite/{invite_token}"
    context = {
        "name": lead.visitor_name or "there",
        "link": link,
    }
    return send_email(
        kind=EmailLog.Kind.ACCOUNT_INVITE,
        to_email=lead.email,
        subject=_SUBJECT,
        body=render(_BODY, context),
        lead=lead,
    )
