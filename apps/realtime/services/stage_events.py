"""
``message.stage`` — the pending indicator's honest half (Architecture v2.8 §14.3,
Backend v7.1 Phase 2).

── THE RULE THIS MODULE EXISTS TO ENFORCE ──────────────────────────────────

The surface shows a visitor one of exactly three sentences while itriX works:

    retrieving   "Retrieving approved material"
    composing    "Composing your answer"
    checking     "Checking before sending"

They advance ONLY when the pipeline actually changes stage. There is no timer, no
interpolation, and no optimistic progression. If a stage cannot be determined, NOTHING IS
SENT and the client holds its current label.

That is the whole design, and it is worth being explicit about why a timer would be
easier and worse. A progress display that advances on its own looks better for one turn.
It costs the visitor's trust in every other statement the surface makes — and this
platform's entire proposition is that what it tells you is governed and true. A surface
that fakes a progress bar has already established that it will say convenient things.

── THREE STAGES, AND EXACTLY THREE ─────────────────────────────────────────
They map to real transitions in the generation pipeline:

    retrieving   retrieval starts — before the first knowledge-core query
    composing    the first generation call is made
    checking     the settle pipeline starts — the Claim-Card re-run

Adding a fourth, softening one, or making one sound busier than it is requires Governance
sign-off, because the strings are a claim about what the system is doing.

── THE WORDING LIVES ON THE FRONTEND ───────────────────────────────────────
This module emits the ENUM. ``itrix-web/src/lib/content/pendingCopy.ts`` holds the three
approved strings. That split is deliberate: a backend change must not be able to silently
reword what a visitor reads, and the copy has one owner (Playbook v1.8 §13.2).
"""

from __future__ import annotations

import logging

logger = logging.getLogger("itrix")

STAGE_RETRIEVING = "retrieving"
STAGE_COMPOSING = "composing"
STAGE_CHECKING = "checking"

# The closed vocabulary. An unknown stage is DROPPED rather than forwarded: the client
# would have no string for it and would fall back to a neutral label, which looks like the
# indicator having stalled.
STAGES: tuple[str, ...] = (STAGE_RETRIEVING, STAGE_COMPOSING, STAGE_CHECKING)

# The order the pipeline actually moves through. Used to refuse a BACKWARD transition —
# see `StageEmitter`.
_ORDER = {STAGE_RETRIEVING: 0, STAGE_COMPOSING: 1, STAGE_CHECKING: 2}


def is_stage(value: object) -> bool:
    return isinstance(value, str) and value in STAGES


def payload(*, thread_id: str, message_id: str, stage: str) -> dict:
    """
    The ``message.stage`` wire payload.

    Carries the stage ENUM and nothing else of substance. No percentage, no elapsed time,
    no estimate, no agent key — a visitor-facing progress event that carried an internal
    agent name would be a §10.5 leak wearing a progress bar.
    """
    return {
        "threadId": str(thread_id or ""),
        "messageId": str(message_id or ""),
        "stage": stage,
    }


class StageEmitter:
    """
    Emits each stage AT MOST ONCE PER TURN, in order.

    ── WHY THE DEDUPLICATION AND THE ORDERING GUARD ARE HERE, NOT AT THE CALL SITE ──

    The pipeline calls into retrieval more than once for some agents, and a naive emitter
    would send ``retrieving`` twice — which reads on screen as the indicator going
    backwards, i.e. as a fault. It would also send ``retrieving`` again AFTER
    ``composing`` for an agent that re-queries mid-generation, which reads as the system
    having lost its place.

    Neither of those is a lie exactly, but both make an honest indicator look broken, and
    an indicator that looks broken is one a visitor stops reading. So:

        · each stage is emitted at most once per turn;
        · a stage that would move BACKWARDS is silently dropped;
        · an unknown stage is dropped and logged.

    Dropping is the right failure here: the client holds its current label, which is the
    documented behaviour when no stage arrives (§3.10). Sending something wrong would be
    worse than sending nothing.

    ``send`` is the transport, injected. This class does not know whether it is talking to
    a socket, a channel layer, or a test double — which is what lets the same emitter serve
    the WebSocket path and the HTTP fallback path without two implementations of the rule.
    """

    def __init__(self, send, *, thread_id: str, message_id: str):
        self._send = send
        self._thread_id = str(thread_id or "")
        self._message_id = str(message_id or "")
        self._sent: set[str] = set()
        self._highest = -1

    async def emit(self, stage: str) -> bool:
        """
        Announce a real pipeline transition. Returns True when something was sent.

        Never raises. A telemetry failure must not affect delivery — the visitor's answer
        matters more than the label above it.
        """
        if not is_stage(stage):
            logger.warning("message.stage: unknown stage %r dropped", stage)
            return False
        if stage in self._sent:
            return False
        rank = _ORDER[stage]
        if rank < self._highest:
            # Backwards. The pipeline re-entered an earlier stage; the visitor does not
            # need to watch that happen.
            return False

        self._sent.add(stage)
        self._highest = rank
        try:
            await self._send(
                {
                    "type": "message.stage",
                    "payload": payload(
                        thread_id=self._thread_id,
                        message_id=self._message_id,
                        stage=stage,
                    ),
                }
            )
            return True
        except Exception:  # noqa: BLE001
            logger.debug("message.stage could not be sent", exc_info=True)
            return False

    @property
    def sent(self) -> frozenset[str]:
        """Which stages went out. Read by tests and by the HTTP path's summary."""
        return frozenset(self._sent)
