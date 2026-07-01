"""
Client-page reveal email builder (reveal ①).

After a visitor's review is diagnosed and their customized client page is revealed, this
sends them the link to it. Qualitative and warm — no quantitative promises (claims
discipline). Delivery is gated by ENABLE_EMAIL_DELIVERY (stubbed otherwise).

The link carries the client_page capability token so the page is reachable without an
account (reveal ①). The token is minted by the journey reveal, passed in here.
"""

from __future__ import annotations

from django.conf import settings

from apps.emails.models import EmailLog
from apps.emails.services.email_sender import send_email
from apps.emails.services.template_renderer import render

_SUBJECT = "Your iTrix computation review is ready"
_BODY = (
    "Hi {{name}},\n\n"
    "We've put together a short, personalized page based on the computation challenge you"
    " described. It walks through what we heard, where {{product_route}} may fit, and a"
    " suggested next step.\n\n"
    "View it here: {{link}}\n\n"
    "You can also ask questions right on the page — our assistant will answer within what"
    " we can share publicly.\n\n"
    "— The iTrix Assessment Team"
)


def build_client_page_reveal_email(lead, *, capability_token: str = "") -> EmailLog:
    base = getattr(settings, "FRONTEND_WEB_URL", "") or ""
    link = f"{base}/r/{capability_token}" if capability_token else f"{base}/result/{lead.id}"
    context = {
        "name": lead.visitor_name or "there",
        "product_route": lead.product_route_display,
        "link": link,
    }
    return send_email(
        kind=EmailLog.Kind.CLIENT_PAGE_REVEAL,
        to_email=lead.email,
        subject=_SUBJECT,
        body=render(_BODY, context),
        lead=lead,
    )
