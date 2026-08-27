"""My Review ready-email builder.

My Review access is browser/session-bound. Email must therefore never carry a reusable
or transferable review credential. This message only tells the recipient to return to
the conversation where the explicit **View My Review** action can mint a one-time code
bound to that browser and exchange it into an httpOnly access session.
"""

from __future__ import annotations

from django.conf import settings

from apps.emails.models import EmailLog
from apps.emails.services.email_sender import send_email
from apps.emails.services.template_renderer import render

_SUBJECT = "Your itriX computation review is ready"
_BODY = (
    "Hi {{name}},\n\n"
    "Your itriX My Review is ready. Return to your itriX conversation and choose "
    "‘View My Review’ to open it securely.\n\n"
    "For your protection, this email does not contain a transferable review-access link "
    "or credential.\n\n"
    "— The itriX Team"
)


def build_client_page_reveal_email(lead, *, capability_token: str = "") -> EmailLog:
    """Build the ready notice without embedding ``capability_token`` or a lead id.

    ``capability_token`` remains in the signature only so an older internal caller cannot
    accidentally break deployment; it is deliberately ignored.
    """
    del capability_token
    # Read for deployment compatibility/documentation only; never interpolate a review URL.
    _ = getattr(settings, "FRONTEND_WEB_URL", "")
    context = {"name": lead.visitor_name or "there"}
    return send_email(
        kind=EmailLog.Kind.CLIENT_PAGE_REVEAL,
        to_email=lead.email,
        subject=_SUBJECT,
        body=render(_BODY, context),
        lead=lead,
    )
