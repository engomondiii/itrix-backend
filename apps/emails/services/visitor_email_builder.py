"""
Visitor email builder.

Generic visitor-facing email used for ad-hoc sends from the dashboard (e.g. sending a
custom message to a lead). Subject + body are provided by the caller; this wraps the
sender with the visitor email kind and records it against the lead.
"""

from __future__ import annotations

from apps.emails.models import EmailLog
from apps.emails.services.email_sender import send_email
from apps.emails.services.template_renderer import render


def build_visitor_email(
    lead,
    *,
    subject: str,
    body: str,
    to_email: str | None = None,
    cc=None,
    attachments=None,
    scheduled_at=None,
    context: dict | None = None,
) -> EmailLog:
    rendered = render(body, context or {})
    return send_email(
        kind=EmailLog.Kind.VISITOR,
        to_email=to_email or (lead.email if lead else ""),
        subject=subject,
        body=rendered,
        lead=lead,
        cc=cc,
        attachments=attachments,
        scheduled_at=scheduled_at,
    )
