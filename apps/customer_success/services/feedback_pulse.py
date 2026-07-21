"""
Private feedback (Playbook §12I).

    This is private. It goes to your customer-success owner and nowhere else.

THREE RULES, and this module is where they become true rather than aspirational:

1. A pulse score is NEVER rendered back to the customer as a judgement about them.
2. It is never used in copy addressed to them.
3. It is never shown outside the success team.

── WHY THE ENDPOINT IS WRITE-ONLY ───────────────────────────────────────────
``submit()`` has no read counterpart on the client plane. There is deliberately no
``get_my_pulses()``. If a customer could read their own pulse history back, the score
would exist in a client-plane payload — and once it exists there, some future surface
will render it. Making it unreadable is the only version of "private" that survives
refactoring.

Scores are also NEVER sent to analytics (§Phase 3 note): an aggregate that can be
filtered to one customer is that customer's score wearing a disguise.
"""

from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger("itrix")

PROMPT = "This is private. It goes to your customer-success owner and nowhere else."
FREE_TEXT_PLACEHOLDER = "Anything you would want us to change."
FOLLOW_UP_OPTION = "I would like someone to follow up on this."


def submit(client, *, score: int | None = None, comment: str = "",
           wants_follow_up: bool = False):
    """
    Record a pulse. WRITE-ONLY from the client plane.

    Returns the created row for the SUCCESS TEAM's use. The client-plane view discards
    it and returns only an acknowledgement — see ``views.py``.
    """
    from apps.customer_success.models import FeedbackPulse

    if score is not None:
        score = max(1, min(5, int(score)))

    pulse = FeedbackPulse.objects.create(
        client=client,
        score=score,
        comment=(comment or "").strip(),
        wants_follow_up=bool(wants_follow_up),
    )

    if pulse.is_negative or pulse.wants_follow_up:
        _alert_success_owner(pulse)

    try:
        from apps.customer_success.services.health_calculator import recompute

        recompute(client)
    except Exception:  # noqa: BLE001
        pass

    logger.info("feedback.pulse recorded for client=%s (follow_up=%s)",
                client.id, pulse.wants_follow_up)
    return pulse


ACKNOWLEDGEMENT = "Thank you — this has gone to your customer-success owner."


def _alert_success_owner(pulse) -> None:
    """
    Alert the named owner on a negative pulse or an explicit follow-up request.

    Best-effort: a failed alert must never surface as an error to the customer, because
    the error would tell them their private feedback was scored.
    """
    try:
        from apps.notifications.services.notification_creator import notify_feedback_risk

        notify_feedback_risk(pulse)
    except Exception:  # noqa: BLE001
        logger.debug("feedback alert skipped (notifier unavailable)")


def recent_for_success_team(client, *, limit: int = 20):
    """
    Pulses for the SUCCESS TEAM only.

    Never call this from a client-plane view. The name is deliberately awkward so a
    mistaken import reads wrong at the call site.
    """
    from apps.customer_success.models import FeedbackPulse

    return FeedbackPulse.objects.filter(client=client).order_by("-created_at")[:limit]


def acknowledge(pulse, *, user=None):
    pulse.acknowledged_at = timezone.now()
    pulse.acknowledged_by = user
    pulse.save(update_fields=["acknowledged_at", "acknowledged_by", "updated_at"])
    return pulse


def has_negative_signal(client, *, window_days: int = 90) -> bool:
    """Read by the customer-first NBA rule as the 'negative trust signal' input."""
    from apps.customer_success.models import FeedbackPulse

    if client is None:
        return False
    cutoff = timezone.now() - timezone.timedelta(days=window_days)
    return FeedbackPulse.objects.filter(
        client=client, created_at__gte=cutoff, score__lte=2
    ).exists()
