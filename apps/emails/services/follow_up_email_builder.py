"""
Follow-up email builder.

Composes the email a team member sends (or that's auto-prepared) when following up on a
lead per its SLA. Qualitative; encourages a concrete next step without over-promising.
"""

from __future__ import annotations

from apps.emails.models import EmailLog
from apps.emails.services.email_sender import send_email
from apps.emails.services.template_renderer import render

_SUBJECT = "Following up on your computation bottleneck"
_BODY = (
    "Hi {{name}},\n\n"
    "Following up on the computation challenge you shared with iTrix. We'd welcome a short"
    " conversation to explore whether {{product_route}} is a fit for your workload.\n\n"
    "{{next_step}}\n\n"
    "If now isn't the right time, just let us know.\n\n"
    "— The iTrix Assessment Team"
)


def build_follow_up_email(lead) -> EmailLog:
    context = {
        "name": lead.visitor_name or "there",
        "product_route": lead.product_route_display,
        "next_step": lead.recommended_next_step or "Reply here and we'll set up a time.",
    }
    return send_email(
        kind=EmailLog.Kind.FOLLOW_UP,
        to_email=lead.email,
        subject=_SUBJECT,
        body=render(_BODY, context),
        lead=lead,
    )
