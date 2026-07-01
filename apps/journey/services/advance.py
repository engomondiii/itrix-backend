"""
journey.advance — the single entry point for every journey transition.

    advance(lead, event, *, actor=None, meta=None) -> AdvanceResult

It validates the transition against ``ALLOWED_TRANSITIONS``, writes the new state onto
the Lead, records an append-only ``JourneyTransition`` (audit + timeline), computes any
reveal descriptor for the resulting state, and triggers downstream fan-out
(notifications / SLA tasks) best-effort. Views MUST NOT set ``lead.journey_state``
directly — they call this.

Invalid transitions raise ``InvalidTransition`` rather than silently mutating state, so
callers can distinguish "already there" (idempotent no-op) from "not allowed".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.journey.models import (
    ALLOWED_TRANSITIONS,
    JourneyEvent,
    JourneyState,
    JourneyTransition,
    STATE_REVEAL,
)
from apps.journey.services.reveal import reveal_for_state

logger = logging.getLogger("itrix")


class InvalidTransition(Exception):
    """Raised when an event is not permitted from the lead's current state."""


@dataclass
class AdvanceResult:
    lead: object
    from_state: str
    to_state: str
    event: str
    changed: bool
    reveal: dict | None
    transition: JourneyTransition | None


def _resolve_target(from_state: str, event: str) -> str | None:
    return ALLOWED_TRANSITIONS.get(from_state, {}).get(event)


@transaction.atomic
def advance(lead, event: str, *, actor=None, meta: dict | None = None) -> AdvanceResult:
    """Validate + apply one journey transition for ``lead`` driven by ``event``."""
    meta = meta or {}
    current = lead.journey_state or JourneyState.ARRIVED
    target = _resolve_target(current, event)

    if target is None:
        # Idempotent tolerance: if the event's usual target equals the current state,
        # treat it as a satisfied no-op rather than an error (safe for retries).
        for _from, mapping in ALLOWED_TRANSITIONS.items():
            if mapping.get(event) == current:
                return AdvanceResult(
                    lead=lead,
                    from_state=current,
                    to_state=current,
                    event=event,
                    changed=False,
                    reveal=reveal_for_state(lead, current),
                    transition=None,
                )
        raise InvalidTransition(
            f"Event {event!r} is not allowed from state {current!r} (lead {lead.id})."
        )

    # Apply the new state.
    lead.journey_state = target

    # Stamp value_delivered_at the first time we reach DIAGNOSED (value has been given).
    update_fields = ["journey_state", "updated_at"]
    if target == JourneyState.DIAGNOSED and getattr(lead, "value_delivered_at", None) is None:
        lead.value_delivered_at = timezone.now()
        update_fields.append("value_delivered_at")

    lead.save(update_fields=update_fields)

    reveal = reveal_for_state(lead, target)
    # Phase 2: push the reveal over the subject's WS channel (no-op when realtime off).
    try:
        from apps.journey.services.reveal import emit_reveal

        emit_reveal(lead, reveal)
    except Exception:  # noqa: BLE001
        pass
    reveal_surface = STATE_REVEAL.get(target, "")

    transition = JourneyTransition.objects.create(
        lead=lead,
        from_state=current,
        to_state=target,
        event=event,
        reveal=reveal_surface or "",
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        meta=meta,
    )

    logger.info("journey.advance lead=%s %s→%s on %s", lead.id, current, target, event)

    _fan_out(lead, from_state=current, to_state=target)

    return AdvanceResult(
        lead=lead,
        from_state=current,
        to_state=target,
        event=event,
        changed=True,
        reveal=reveal,
        transition=transition,
    )


def _fan_out(lead, *, from_state: str, to_state: str) -> None:
    """
    Best-effort downstream fan-out on key states (Backend v4 §Phase 2 wires the real
    notification/SLA creators). In Phase 1 this is a safe hook that logs and never
    raises, so the funnel is unaffected whether or not those apps react.
    """
    if to_state not in {
        JourneyState.DIAGNOSED,
        JourneyState.INVITED,
        JourneyState.CLIENT,
        JourneyState.ENGAGED,
    }:
        return

    # Phase 2: real fan-out — team notification + (for later states) an SLA follow-up
    # task. Both are best-effort so a notification hiccup never breaks a transition.
    try:
        from apps.notifications.services.notification_creator import notify_journey_event

        notify_journey_event(lead, to_state=to_state)
    except Exception:  # noqa: BLE001
        logger.exception("journey notification fan-out failed for lead %s", getattr(lead, "id", "?"))

    try:
        from apps.follow_up.services.task_creator import create_journey_task

        create_journey_task(lead, to_state=to_state)
    except Exception:  # noqa: BLE001
        logger.exception("journey task fan-out failed for lead %s", getattr(lead, "id", "?"))


# ── Convenience wrappers for the common transitions ──────────────────────────
def mark_diagnosed(lead, *, meta: dict | None = None) -> AdvanceResult:
    """ARRIVED/IN_REVIEW → DIAGNOSED (value delivered)."""
    return advance(lead, JourneyEvent.QUALIFY, meta=meta)


def reveal_client_page(lead, *, meta: dict | None = None) -> AdvanceResult:
    """DIAGNOSED → CLIENT_PAGE (reveal ①)."""
    return advance(lead, JourneyEvent.REVEAL_CLIENT_PAGE, meta=meta)


def accept_invite(lead, *, actor=None, meta: dict | None = None) -> AdvanceResult:
    """INVITED → CLIENT (reveal ③, client created)."""
    return advance(lead, JourneyEvent.ACCEPT_INVITE, actor=actor, meta=meta)
