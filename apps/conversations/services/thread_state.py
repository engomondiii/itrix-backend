"""
Thread journey state — the ONE place a thread's qualification state advances.

── THE PROBLEM THIS SOLVES ──────────────────────────────────────────────────
Journey state has historically lived only on the Lead. But an anonymous visitor
has NO lead until they qualify or register, and the live conversational surface
(``apps/conversations``) is what an anonymous visitor actually talks to. So there
was nowhere to record that an anonymous conversation had moved from ARRIVED (1)
to IN_REVIEW (2) to DIAGNOSED (3), and the turn path could not advance it. Every
"proceed" re-started the intro, because the state never moved and the model was
never told where the conversation was.

This module gives the turn path a state anchor that works BOTH ways:

    * lead present  -> the Lead remains the source of truth. We call the existing
                       ``journey.services.advance`` engine (single writer, audited,
                       fires reveals) and mirror the resulting state onto the thread
                       so a reader never has to join back to the lead.
    * no lead       -> the thread's own ``current_state`` column IS the state. We
                       move it forward directly (ARRIVED -> IN_REVIEW -> DIAGNOSED),
                       which is the full anonymous band; anything past DIAGNOSED
                       requires an identified subject and therefore a lead.

Coverage, the stop rule, the question generator and the memory assembler are all
already thread-centric and lead-free — this is the last lead-bound piece they
needed, and it is deliberately the ONLY thing here that knows how to move state.

── FORWARD-ONLY ─────────────────────────────────────────────────────────────
State only ever moves forward. A retried turn that asks to enter IN_REVIEW when
already at DIAGNOSED is a satisfied no-op, never a downgrade — mirrored on the
``advance`` engine's own idempotence.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("itrix")

# The anonymous qualification band, in order. These are the only states an
# anonymous (lead-less) thread can occupy; everything past DIAGNOSED needs an
# identified subject and therefore a lead.
_ANON_ORDER = {"ARRIVED": 1, "IN_REVIEW": 2, "DIAGNOSED": 3}
_ANON_BY_NUMBER = {1: "ARRIVED", 2: "IN_REVIEW", 3: "DIAGNOSED"}


def current_state_key(thread) -> str:
    """
    The thread's current journey state as a state key (e.g. ``IN_REVIEW``).

    Prefers the lead when one exists (the lead is the source of truth), else the
    thread's own ``current_state`` column. Always normalised.
    """
    from apps.journey.models import normalize_state

    lead = getattr(thread, "lead", None)
    if lead is not None:
        return normalize_state(getattr(lead, "journey_state", None))
    return normalize_state(getattr(thread, "current_state", None) or "ARRIVED")


def current_state_number(thread) -> int:
    """The thread's current journey state as a number 1..10 (1 when unknown)."""
    from apps.journey.models import journey_number

    return journey_number(current_state_key(thread)) or 1


def _mirror_onto_thread(thread, state_key: str) -> None:
    """Keep the thread's denormalised ``current_state`` in step with the lead."""
    try:
        if getattr(thread, "current_state", None) != state_key:
            thread.current_state = state_key
            thread.save(update_fields=["current_state", "updated_at"])
    except Exception:  # noqa: BLE001 - a mirror failure must never break a turn
        logger.debug("could not mirror current_state onto thread %s", getattr(thread, "id", "?"))


def enter_in_review(thread) -> None:
    """
    Move the thread from ARRIVED (1) to IN_REVIEW (2) — the first-turn transition.

    Idempotent: calling it on a thread already at or past IN_REVIEW is a no-op.
    When a lead exists this defers to ``advance.on_first_turn`` so the reveal and
    audit trail happen exactly as they do for identified subjects.
    """
    lead = getattr(thread, "lead", None)
    if lead is not None:
        try:
            from apps.journey.services.advance import on_first_turn

            result = on_first_turn(lead, thread=thread)
            _mirror_onto_thread(thread, getattr(result, "to_state", None) or current_state_key(thread))
        except Exception:  # noqa: BLE001 - an invalid transition mid-journey is expected
            logger.debug("first-turn advance skipped for lead %s", getattr(lead, "id", "?"))
        return

    # Lead-less: move the thread's own state forward, forward-only.
    if _ANON_ORDER.get(getattr(thread, "current_state", "ARRIVED"), 1) < _ANON_ORDER["IN_REVIEW"]:
        _mirror_onto_thread(thread, "IN_REVIEW")


def close_qualification_loop(thread, *, reason: str = "") -> bool:
    """
    Close the qualification loop: move to DIAGNOSED (2 -> 3) and fire the handoff.

    Returns True when the state actually moved (so the caller can generate the
    reflection / stop suggesting questions), False when it was already closed.

    When a lead exists this defers to ``advance.on_loop_closed`` — which fires the
    ``LOOP_CLOSED`` event, triggers reflection-artifact generation and emits the
    shell update. When there is no lead we move the thread's own state to DIAGNOSED
    and emit a shell update directly so the open transcript reacts live.
    """
    from apps.journey.models import journey_number

    # Already closed? Nothing to do.
    if journey_number(current_state_key(thread)) and journey_number(current_state_key(thread)) >= 3:
        return False

    lead = getattr(thread, "lead", None)
    if lead is not None:
        try:
            from apps.journey.services.advance import on_loop_closed

            result = on_loop_closed(lead, thread=thread, meta={"reason": reason} if reason else None)
            _mirror_onto_thread(thread, getattr(result, "to_state", None) or "DIAGNOSED")
            return bool(getattr(result, "changed", True))
        except Exception:  # noqa: BLE001
            logger.debug("loop-closed advance skipped for lead %s", getattr(lead, "id", "?"))
            return False

    # Lead-less: move the thread to DIAGNOSED and push a shell update so the
    # visitor's surface leaves the question loop immediately.
    if _ANON_ORDER.get(getattr(thread, "current_state", "ARRIVED"), 1) >= _ANON_ORDER["DIAGNOSED"]:
        return False
    _mirror_onto_thread(thread, "DIAGNOSED")
    _emit_anonymous_shell_update(thread)
    return True


def _emit_anonymous_shell_update(thread) -> None:
    """Push a fresh shell contract for a lead-less thread onto its socket group."""
    try:
        from apps.conversations.services.fan_out import broadcast_shell_update
        from apps.journey.services import shell

        contract = shell.for_anonymous_thread(thread)
        broadcast_shell_update(thread.group_name, contract)
    except Exception:  # noqa: BLE001 - a fan-out hiccup must never break a turn
        logger.debug("anonymous shell update fan-out failed for thread %s", getattr(thread, "id", "?"))
