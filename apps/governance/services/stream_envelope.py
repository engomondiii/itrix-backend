"""
Streaming governance, Part 1 — the pre-flight envelope (Backend v6.0 §6.1).

v5.0 ran governance as the final pipeline stage on a COMPLETED message. Streaming
renders text before the message is complete, so a single terminal gate is no longer
sufficient. v6.0 uses a three-part model and ALL THREE PARTS ARE REQUIRED:

    Part 1  pre-flight envelope   (this module)     — what may stream AT ALL
    Part 2  stream guard          (stream_guard.py) — hard halt mid-stream
    Part 3  settle                (claim_checker)   — the full Claim-Card pipeline

── WHAT THIS PART DOES ──────────────────────────────────────────────────────
BEFORE a single token is streamed, the turn is bound to a claim ceiling derived from the
plane, the state and the retrieved chunks. Only content whose claim level is at or below
``AGENT_AUTO_APPROVE_MAX_LEVEL`` may stream at all.

A turn that would require LEVEL-4 OR LEVEL-5 approval DOES NOT STREAM. The visitor
immediately sees the approved under-review wording and the turn enters the approval
queue.

NOTHING ABOUT A HIGH-RISK CLAIM IS EVER RENDERED PROVISIONALLY. That is the whole point
of doing this before generation rather than after: a level-5 claim that streams for two
seconds and is then retracted has already been read.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.conf import settings

logger = logging.getLogger("itrix")

# The exact approved wording shown when a turn may not stream. Playbook v1.6 §13.3.
# DO NOT REWORD WITHOUT GOVERNANCE SIGN-OFF. This string and the halted string are the
# ONLY things a visitor sees when governance intervenes. They must be calm, must not
# over-apologise, and must never explain what was blocked or why.
UNDER_REVIEW_WORDING = (
    "A specialist is reviewing this response before we share it. "
    "We will update this message shortly."
)

HALTED_WORDING = (
    "We stopped that response before it finished. "
    "A specialist is preparing an accurate answer for you now."
)

# Claim levels that can NEVER stream, regardless of the auto-approve threshold.
NEVER_STREAM_LEVELS = frozenset({4, 5})


@dataclass
class StreamEnvelope:
    """The binding decision made before generation begins."""

    may_stream: bool
    claim_ceiling: int
    plane: str
    reason: str = ""
    # The wording to send immediately when streaming is refused.
    replacement_body: str = ""
    # Contextual notes for the cockpit (never visitor-facing).
    notes: list[str] = field(default_factory=list)

    @property
    def requires_approval(self) -> bool:
        return not self.may_stream


def auto_approve_max_level() -> int:
    return int(getattr(settings, "AGENT_AUTO_APPROVE_MAX_LEVEL", 2))


def stream_guard_enabled() -> bool:
    return bool(getattr(settings, "STREAM_GUARD_ENABLED", True))


# The maximum claim level each plane may reach. A plane can never be widened by the
# state, by the prompt, or by an attachment.
_PLANE_MAX_CLAIM = {
    "public": 2,
    "anonymous": 2,
    "client": 3,
    "team": 5,
}

# States that inherently carry higher-risk claims (performance, pricing, exclusivity).
# Reaching one of these does NOT raise the plane's ceiling; it only lowers ours further
# when the plane would otherwise have allowed more.
_STATE_CLAIM_CAP = {
    1: 1,   # arrival: may ask, never assert
    2: 2,
    3: 2,
    4: 2,
    5: 2,
    6: 3,
    7: 3,
    8: 3,
    9: 3,
    10: 3,
}


def build(
    *,
    plane: str = "public",
    journey_state: int | None = None,
    intended_claim_level: int = 1,
    retrieved_chunk_levels: list[int] | None = None,
) -> StreamEnvelope:
    """
    Bind a turn to a claim ceiling BEFORE any token is generated.

    ``intended_claim_level`` is what the agent believes it is about to say;
    ``retrieved_chunk_levels`` are the claim levels of the approved chunks it will answer
    from. The effective level is the HIGHEST of the two — answering from a level-4 chunk
    is a level-4 claim regardless of how the agent framed its intent.
    """
    plane_cap = _PLANE_MAX_CLAIM.get(plane, 2)
    state_cap = _STATE_CLAIM_CAP.get(journey_state or 1, 2)
    ceiling = min(plane_cap, state_cap, auto_approve_max_level())

    effective = max(int(intended_claim_level or 1), *(retrieved_chunk_levels or [0]) or [0])

    notes = [
        f"plane={plane} plane_cap={plane_cap}",
        f"state={journey_state} state_cap={state_cap}",
        f"auto_approve_max={auto_approve_max_level()}",
        f"effective_claim_level={effective}",
    ]

    if effective in NEVER_STREAM_LEVELS:
        logger.info(
            "stream_envelope: refusing to stream level-%s claim on plane=%s", effective, plane
        )
        return StreamEnvelope(
            may_stream=False,
            claim_ceiling=ceiling,
            plane=plane,
            reason=f"claim_level_{effective}_requires_approval",
            replacement_body=UNDER_REVIEW_WORDING,
            notes=notes,
        )

    if effective > ceiling:
        return StreamEnvelope(
            may_stream=False,
            claim_ceiling=ceiling,
            plane=plane,
            reason="claim_level_exceeds_envelope",
            replacement_body=UNDER_REVIEW_WORDING,
            notes=notes,
        )

    return StreamEnvelope(
        may_stream=True,
        claim_ceiling=ceiling,
        plane=plane,
        reason="",
        notes=notes,
    )


def for_context(ctx, *, intended_claim_level: int = 1) -> StreamEnvelope:
    """Convenience: build an envelope straight from an ``AgentContext``."""
    plane = getattr(ctx, "plane", "public")
    journey_state = None
    lead_id = getattr(ctx, "lead_id", None)
    if lead_id:
        try:
            from apps.journey.models import journey_number
            from apps.leads.models import Lead

            lead = Lead.objects.filter(id=lead_id).only("journey_state").first()
            if lead is not None:
                journey_state = journey_number(lead.journey_state)
        except Exception:  # noqa: BLE001
            journey_state = None
    return build(
        plane=plane,
        journey_state=journey_state,
        intended_claim_level=intended_claim_level,
    )
