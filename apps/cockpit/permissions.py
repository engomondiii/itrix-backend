"""
Role gates for the cockpit (Architecture v2.8 §18, Backend v7.1 §Phase 1).

Every route in this app is TEAM PLANE ONLY and reads §10.5 internal-only material. The
finer gate below exists for one field.

── matchedText IS THE MOST SENSITIVE FIELD ON SURFACE 2 ────────────────────
It is the prohibited wording a model tried to emit. Showing it to an operator is
correct — they cannot diagnose retrieval drift from a pattern identifier alone — but it
is the platform's own unapproved language, in plain text, and the decision of 21 July
limits it to ADMIN and ASSESSMENT.

THE FILTER IS SERVER-SIDE, and that is the load-bearing part. A frontend that hid the
field would still have received it: the bytes would be in the JSON, in the browser cache,
and in anything that logged the response. A VIEWER receives the pattern identifier and
nothing more, because the text never leaves this process for them.
"""

from __future__ import annotations

from apps.core.permissions import ROLE_ADMIN, ROLE_ASSESSMENT


def may_see_matched_text(user) -> bool:
    """
    True for ADMIN and ASSESSMENT only.

    Fails CLOSED on anything unexpected — a missing role attribute, an anonymous user, a
    user object from a future auth backend. The cost of failing closed is an operator who
    has to ask a colleague; the cost of failing open is the platform's prohibited wording
    in a role that was never reviewed for it.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if not getattr(user, "is_active", False):
        return False
    return getattr(user, "role", None) in {ROLE_ADMIN, ROLE_ASSESSMENT}
