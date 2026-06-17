"""
Confirmation email builder.

Sends the visitor a confirmation after they complete the review / leave their email.
Qualitative and warm; no quantitative promises (claims discipline).
"""

from __future__ import annotations

from apps.emails.models import EmailLog
from apps.emails.services.email_sender import send_email
from apps.emails.services.template_renderer import render

_SUBJECT = "We received your computation bottleneck review"
_BODY = (
    "Hi {{name}},\n\n"
    "Thanks for sharing your computation challenge with iTrix. We've received your review"
    " and our team is taking a look.\n\n"
    "Based on what you described, the most relevant entry point looks like {{product_route}}."
    " {{next_step}}\n\n"
    "We'll be in touch shortly.\n\n"
    "— The iTrix Assessment Team"
)


def build_confirmation_email(lead) -> EmailLog:
    context = {
        "name": lead.visitor_name or "there",
        "product_route": lead.product_route_display,
        "next_step": lead.recommended_next_step or "We'll share relevant next steps.",
    }
    return send_email(
        kind=EmailLog.Kind.CONFIRMATION,
        to_email=lead.email,
        subject=_SUBJECT,
        body=render(_BODY, context),
        lead=lead,
    )
