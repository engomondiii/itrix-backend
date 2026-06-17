"""
Internal alert builder.

Emails the IWL team inbox when a noteworthy lead arrives (used by the lead-creation
fan-out). Tier 1 leads get a stronger subject. Recipient is INTERNAL_ALERT_EMAIL.
"""

from __future__ import annotations

from django.conf import settings

from apps.emails.models import EmailLog
from apps.emails.services.email_sender import send_email
from apps.emails.services.template_renderer import render

_BODY = (
    "New lead in the pipeline.\n\n"
    "Organization : {{company}}\n"
    "Tier         : {{tier}}  (score {{score}}/100)\n"
    "Product route: {{product_route}}\n"
    "Commercial   : {{commercial_path}}\n"
    "Primary pain : {{primary_pain}}\n"
    "Handoff      : {{handoff}}\n\n"
    "Open the lead: {{href}}\n"
)


def build_internal_alert(lead) -> EmailLog:
    to_email = getattr(settings, "INTERNAL_ALERT_EMAIL", "") or getattr(settings, "EMAIL_FROM", "") or "team@itrix.example"
    who = lead.company or lead.visitor_name or "Unknown org"
    tier_marker = "Tier 1 STRATEGIC " if lead.tier == 1 else ""
    context = {
        "company": who,
        "tier": lead.tier,
        "score": lead.score,
        "product_route": lead.product_route_display,
        "commercial_path": lead.commercial_path_display,
        "primary_pain": lead.primary_pain or "n/a",
        "handoff": "YES" if lead.human_handoff_trigger else "no",
        "href": f"/leads/{lead.id}",
    }
    return send_email(
        kind=EmailLog.Kind.INTERNAL_ALERT,
        to_email=to_email,
        subject=f"{tier_marker}New lead: {who} (T{lead.tier}, {lead.score})",
        body=render(_BODY, context),
        lead=lead,
    )
