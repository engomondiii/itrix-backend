"""
journey.advance — the single entry point for every journey transition.

    advance(lead, event, *, actor=None, meta=None, thread=None) -> AdvanceResult

It validates the transition against ``ALLOWED_TRANSITIONS``, writes the new state onto
the Lead (including its denormalised ``journey_number`` / ``state_key``), records an
append-only ``JourneyTransition``, computes any reveal, emits ``journey.reveal`` +
``shell.update``, and triggers downstream fan-out best-effort.

Views MUST NOT set ``lead.journey_state`` directly — they call this. State has EXACTLY
ONE WRITER (Architecture v2.6 §11.9).

── v6.0: TRANSITIONS ARE DRIVEN BY CONVERSATION EVENTS ──────────────────────
In v2.5 a transition was triggered by a route arrival. In v2.6 it is triggered by
something that happened IN THE THREAD:

    first turn posted on an empty thread   -> 1 → 2   (``on_first_turn``)
    stop rule fires for qualification band -> 2 → 3   (``on_loop_closed``)
    NDA signed                             -> reveal 4, ceiling raised
    first payment recorded                 -> reveal 5, overlay activated, 6 → 7
    contract executed                      -> reveal 6, 9 → 10

A transition NEVER navigates the visitor. It appends to the thread and updates the
shell contract.

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
    EVENT_REVEAL,
    STATE_REVEAL,
    JourneyEvent,
    JourneyState,
    JourneyTransition,
    journey_number,
    normalize_state,
)
from apps.journey.services.reveal import (
    emit_reveal,
    emit_shell_update,
    reveal_for_event,
    reveal_for_state,
)

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
    journey_number: int | None = None


def _resolve_target(from_state: str, event: str) -> str | None:
    return ALLOWED_TRANSITIONS.get(from_state, {}).get(event)


@transaction.atomic
def advance(
    lead,
    event: str,
    *,
    actor=None,
    meta: dict | None = None,
    thread=None,
) -> AdvanceResult:
    """Validate + apply one journey transition for ``lead`` driven by ``event``."""
    meta = dict(meta or {})
    if thread is not None:
        meta.setdefault("thread_id", str(getattr(thread, "id", "")))

    # Read the RAW stored value so a deprecated row still resolves its own transitions,
    # but normalise for everything downstream.
    raw_current = getattr(lead, "journey_state", None) or JourneyState.ARRIVED.value
    current = raw_current if raw_current in ALLOWED_TRANSITIONS else normalize_state(raw_current)
    target = _resolve_target(current, event)

    if target is None:
        # Idempotent tolerance: if the event's usual target equals the current state,
        # treat it as a satisfied no-op rather than an error (safe for retries).
        normalized_current = normalize_state(current)
        for mapping in ALLOWED_TRANSITIONS.values():
            if normalize_state(mapping.get(event) or "") == normalized_current and mapping.get(event):
                return AdvanceResult(
                    lead=lead,
                    from_state=current,
                    to_state=current,
                    event=event,
                    changed=False,
                    reveal=reveal_for_state(lead, current),
                    transition=None,
                    journey_number=journey_number(current),
                )
        raise InvalidTransition(
            f"Event {event!r} is not allowed from state {current!r} (lead {lead.id})."
        )

    # A self-transition (e.g. NDA_SIGNED inside NDA_REVIEW) is a real, audited event
    # even though the state value does not move.
    state_moved = target != current

    lead.journey_state = target
    update_fields = ["journey_state", "updated_at"]

    # Denormalised ladder fields — kept in lockstep so no reader has to recompute them.
    number = journey_number(target)
    if hasattr(lead, "journey_number"):
        lead.journey_number = number
        update_fields.append("journey_number")
    if hasattr(lead, "state_key"):
        lead.state_key = target
        update_fields.append("state_key")

    # Stamp value_delivered_at the first time we reach DIAGNOSED (value has been given).
    if target == JourneyState.DIAGNOSED.value and getattr(lead, "value_delivered_at", None) is None:
        lead.value_delivered_at = timezone.now()
        update_fields.append("value_delivered_at")

    lead.save(update_fields=update_fields)

    # A reveal may be fired by the RESULTING STATE or by the EVENT itself (reveal 4).
    reveal = reveal_for_event(lead, event, target) or (
        reveal_for_state(lead, target) if state_moved else None
    )
    reveal_surface = EVENT_REVEAL.get(event) or (STATE_REVEAL.get(target, "") if state_moved else "")

    # Push the reveal AND the shell update so the open transcript reacts live.
    emit_reveal(lead, reveal)
    emit_shell_update(lead, thread=thread)

    transition = JourneyTransition.objects.create(
        lead=lead,
        from_state=current,
        to_state=target,
        event=event,
        reveal=reveal_surface or "",
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        meta=meta,
    )

    logger.info(
        "journey.advance lead=%s %s->%s (#%s) on %s",
        lead.id,
        current,
        target,
        number,
        event,
    )

    _phase2_hooks(lead, event=event, to_state=target, thread=thread)
    _fan_out(lead, from_state=current, to_state=target, event=event)

    return AdvanceResult(
        lead=lead,
        from_state=current,
        to_state=target,
        event=event,
        changed=state_moved,
        reveal=reveal,
        transition=transition,
        journey_number=number,
    )


def _phase2_hooks(lead, *, event: str, to_state: str, thread=None) -> None:
    """
    v6.0 Phase 2 side effects (Backend v6.0 §Phase 2).

        FIRST_PAYMENT      -> overlay.activate()      (R16 — success at first payment)
        CONTRACT_EXECUTED  -> ceiling -> customer_contract
        LOOP_CLOSED        -> artifacts.generate()    (§5.5 — the stop-rule handoff)

    Every hook is best-effort. A transition that has already been written must never be
    rolled back because a downstream artifact failed to render.
    """
    if event == JourneyEvent.FIRST_PAYMENT.value or to_state == JourneyState.ASSESSMENT.value:
        _activate_success_overlay(lead)

    if event == JourneyEvent.CONTRACT_EXECUTED.value:
        _mark_contracted(lead)

    if event == JourneyEvent.LOOP_CLOSED.value and thread is not None:
        _generate_qualification_artifacts(thread)


def _activate_success_overlay(lead) -> None:
    """Reveal 5. Idempotent — a retried transition must not duplicate the team."""
    try:
        from apps.clients.models import Client
        from apps.customer_success.services import overlay

        client = getattr(lead, "client", None) or Client.objects.filter(lead=lead).first()
        if client is not None:
            overlay.activate(client)
    except Exception:  # noqa: BLE001
        logger.exception("success overlay activation failed for lead %s", getattr(lead, "id", "?"))


def _mark_contracted(lead) -> None:
    """Reveal 6 — the ceiling rises to customer_contract."""
    try:
        from apps.clients.models import Client

        client = getattr(lead, "client", None) or Client.objects.filter(lead=lead).first()
        if client is not None and (client.contract_state or "") not in {"executed", "active"}:
            client.contract_state = "executed"
            client.save(update_fields=["contract_state", "updated_at"])
    except Exception:  # noqa: BLE001
        logger.exception("contract state update failed for lead %s", getattr(lead, "id", "?"))


def _generate_qualification_artifacts(thread) -> None:
    """
    §5.5: reflection, then the pitch room, then advance. NO FURTHER QUESTION IS ASKED.
    """
    from django.conf import settings

    if not getattr(settings, "ENABLE_ADAPTIVE_QUESTIONS", False):
        return
    try:
        from tasks.artifact_tasks import generate_qualification_artifacts

        generate_qualification_artifacts(str(thread.id))
    except Exception:  # noqa: BLE001
        logger.exception("qualification artifact generation failed")


def _fan_out(lead, *, from_state: str, to_state: str, event: str = "") -> None:
    """
    Best-effort downstream fan-out on key states. Both hooks are wrapped so a
    notification hiccup never breaks a transition.
    """
    if to_state not in {
        JourneyState.DIAGNOSED.value,
        JourneyState.INVITED.value,
        JourneyState.NDA_REVIEW.value,
        JourneyState.ASSESSMENT.value,
        JourneyState.POC.value,
        JourneyState.INTEGRATION.value,
        JourneyState.CUSTOMER_SUCCESS.value,
    }:
        return

    try:
        from apps.notifications.services.notification_creator import notify_journey_event

        notify_journey_event(lead, to_state=to_state)
    except Exception:  # noqa: BLE001
        logger.exception(
            "journey notification fan-out failed for lead %s", getattr(lead, "id", "?")
        )

    try:
        from apps.follow_up.services.task_creator import create_journey_task

        create_journey_task(lead, to_state=to_state)
    except Exception:  # noqa: BLE001
        logger.exception("journey task fan-out failed for lead %s", getattr(lead, "id", "?"))


# ── Convenience wrappers for the common transitions ──────────────────────────
def mark_diagnosed(lead, *, meta: dict | None = None) -> AdvanceResult:
    """ARRIVED/IN_REVIEW → DIAGNOSED (value delivered)."""
    return advance(lead, JourneyEvent.QUALIFY.value, meta=meta)


def reveal_client_page(lead, *, meta: dict | None = None) -> AdvanceResult:
    """DIAGNOSED → CLIENT_PAGE (reveal 1)."""
    return advance(lead, JourneyEvent.REVEAL_CLIENT_PAGE.value, meta=meta)


def accept_invite(lead, *, actor=None, meta: dict | None = None) -> AdvanceResult:
    """INVITED → NDA_REVIEW (reveal 3, client created)."""
    return advance(lead, JourneyEvent.ACCEPT_INVITE.value, actor=actor, meta=meta)


# ── v6.0 conversation-driven entry points ────────────────────────────────────
def on_first_turn(lead, *, thread=None, meta: dict | None = None) -> AdvanceResult:
    """
    A turn was posted on an empty thread: 1 → 2.

    Idempotent — a second turn on an already-IN_REVIEW thread is a satisfied no-op, not
    an error, because ingest calls this on every turn without tracking whether it is the
    first.
    """
    return advance(lead, JourneyEvent.FIRST_TURN.value, meta=meta, thread=thread)


def on_loop_closed(lead, *, thread=None, meta: dict | None = None) -> AdvanceResult:
    """
    The deterministic stop rule fired for the qualification band: 2 → 3.

    Phase 2 hangs artifact generation off this transition (``artifacts.generate(thread,
    "reflection")``); Phase 1 records the state move so the shell contract is already
    correct when that lands.
    """
    return advance(lead, JourneyEvent.LOOP_CLOSED.value, meta=meta, thread=thread)


def on_nda_signed(lead, *, actor=None, meta: dict | None = None) -> AdvanceResult:
    """NDA signed — reveal 4, ceiling raised. The state does not move."""
    return advance(lead, JourneyEvent.NDA_SIGNED.value, actor=actor, meta=meta)


def on_first_payment(lead, *, actor=None, meta: dict | None = None) -> AdvanceResult:
    """First payment recorded — reveal 5, overlay activated: 6 → 7."""
    return advance(lead, JourneyEvent.FIRST_PAYMENT.value, actor=actor, meta=meta)


def on_poc_start(lead, *, actor=None, meta: dict | None = None) -> AdvanceResult:
    """PoC started: 7 → 8."""
    return advance(lead, JourneyEvent.POC_START.value, actor=actor, meta=meta)


def on_integration_start(lead, *, actor=None, meta: dict | None = None) -> AdvanceResult:
    """Integration started: 8 → 9."""
    return advance(lead, JourneyEvent.INTEGRATION_START.value, actor=actor, meta=meta)


def on_contract_executed(lead, *, actor=None, meta: dict | None = None) -> AdvanceResult:
    """Contract executed — reveal 6, ceiling → customer_contract: 9 → 10."""
    return advance(lead, JourneyEvent.CONTRACT_EXECUTED.value, actor=actor, meta=meta)
