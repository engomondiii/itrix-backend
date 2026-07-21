"""
Journey models (Backend v6.0 §3, Architecture v2.6 §11).

The progressive-disclosure state machine. ONE explicit ``JourneyState`` governs which
artifacts a subject may receive, which sidebar sections render, and which reveals fire.
State lives on the Lead; this app owns the enum, the reveal vocabulary, and the
append-only transition log.

Nothing here mutates a Lead directly — transitions go through
``apps.journey.services.advance.advance()``, which validates the transition, records a
``JourneyTransition`` row, emits the reveal + shell update, and triggers fan-out. Views
MUST NEVER set state directly (Architecture v2.6 §11.9: "state has exactly one writer").

── v6.0: TEN NUMBERED STATES ────────────────────────────────────────────────
v4.0 shipped nine states ending in a single catch-all ``ENGAGED``. v6.0 numbers the
ladder 1..10 and splits ENGAGED into three first-class states:

    1  ARRIVED           anonymous visitor, empty thread
    2  IN_REVIEW         listening and clarification
    3  DIAGNOSED         personalized reflection delivered
    4  CLIENT_PAGE       personalized pitch room
    5  INVITED           qualified pathway; workspace unlocked
    6  NDA_REVIEW        NDA and confidential review     (was: CLIENT)
    7  ASSESSMENT        paid Alpha Compute Assessment   (was: part of ENGAGED)
    8  POC               paid proof of concept           (was: part of ENGAGED)
    9  INTEGRATION       integration and license-out     (was: part of ENGAGED)
    10 CUSTOMER_SUCCESS  value realization

``DORMANT`` is RETAINED as an OFF-LADDER state — a real value with no journey_number.

``CLIENT`` and ``ENGAGED`` are retained for ONE RELEASE as deprecated aliases so any row
not yet touched by migration 0003 still deserialises. Backend v6.0 Phase 3 drops them
(migration 0005). Do not write new code against them.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import BaseModel
from apps.journey.constants import (
    JOURNEY_NUMBERS,
    OFF_LADDER_STATES,
    STATE_CEILING,
)


class JourneyState(models.TextChoices):
    """
    The ten numbered states plus off-ladder DORMANT and the two deprecated aliases.

        ARRIVED ─first turn─▶ IN_REVIEW ─loop closed─▶ DIAGNOSED
                                                          │ (reveal ① client page)
                                                          ▼
                                                    CLIENT_PAGE
                                               ┌─────────┴─────────┐
                                  gate=true    │                   │  gate=false
                               (reveal ②)      ▼                   ▼
                                            INVITED            DORMANT ◀─┐ returns w/
                                               │ accept                  │ stronger
                                  (reveal ③)   ▼                         │ signal
                                          NDA_REVIEW ────────────────────┘
                                               │ first payment (reveal ⑤ overlay)
                                               ▼
                                          ASSESSMENT ─poc─▶ POC ─integration─▶ INTEGRATION
                                                                                    │
                                                             contract executed (reveal ⑥)
                                                                                    ▼
                                                                          CUSTOMER_SUCCESS
    """

    ARRIVED = "ARRIVED", "Arrived"
    IN_REVIEW = "IN_REVIEW", "In review"
    DIAGNOSED = "DIAGNOSED", "Diagnosed"
    CLIENT_PAGE = "CLIENT_PAGE", "Client page"
    INVITED = "INVITED", "Invited"
    NDA_REVIEW = "NDA_REVIEW", "NDA review"
    ASSESSMENT = "ASSESSMENT", "Assessment"
    POC = "POC", "PoC"
    INTEGRATION = "INTEGRATION", "Integration"
    CUSTOMER_SUCCESS = "CUSTOMER_SUCCESS", "Customer success"
    # Off-ladder.
    DORMANT = "DORMANT", "Dormant"

    # ── The deprecated CLIENT and ENGAGED members were REMOVED in Phase 3 ────
    # (migration 0005). They survived exactly one release as aliases so that any row
    # migration 0003 had not yet touched could still deserialise. That window has closed.
    #
    # ``normalize_state`` still maps the old VALUES forward, because a row written by a
    # process that has not restarted is not a reason to fail a read — but the enum no
    # longer offers them, so nothing new can be written with them.


# The states that are actually part of the ladder (excludes DORMANT + deprecated).
LADDER_STATES: tuple[str, ...] = tuple(JOURNEY_NUMBERS)

# Legacy values and where a read path treats them as pointing.
#
# The ENUM MEMBERS are gone (Phase 3); these raw strings remain as a READ-SIDE mapping so
# a stale row cannot break a page render. Writing them is impossible — they are not
# offered by the enum and not present in ALLOWED_TRANSITIONS.
LEGACY_STATE_ALIASES: dict[str, str] = {
    "CLIENT": JourneyState.NDA_REVIEW.value,
    "ENGAGED": JourneyState.ASSESSMENT.value,
}

# Kept under the old name for one more release so any external import still resolves.
DEPRECATED_STATE_ALIASES = LEGACY_STATE_ALIASES


def normalize_state(state: str | None) -> str:
    """
    Map any stored value to a live state.

    Unknown / empty / deprecated values collapse to the LEAST-PRIVILEGED sensible state
    rather than raising, so a stale row can never widen what a subject may see:

    * empty / unknown  -> ARRIVED   (state 1, public ceiling — minimum privilege)
    * CLIENT           -> NDA_REVIEW
    * ENGAGED          -> ASSESSMENT

    This is the read-side counterpart to migration 0003: the migration fixes the rows;
    this makes every read path safe in the window before (and if) it runs.
    """
    if not state:
        return JourneyState.ARRIVED.value
    if state in LEGACY_STATE_ALIASES:
        return LEGACY_STATE_ALIASES[state]
    if state in JOURNEY_NUMBERS or state in OFF_LADDER_STATES:
        return state
    return JourneyState.ARRIVED.value


def journey_number(state: str | None) -> int | None:
    """1..10 for a ladder state; ``None`` for DORMANT."""
    return JOURNEY_NUMBERS.get(normalize_state(state))


def ceiling_for_state(state: str | None) -> str:
    """The disclosure ceiling this state may reach (never raises a plane's ceiling)."""
    number = journey_number(state)
    if number is None:
        # DORMANT authorizes public + educational surfaces only.
        return STATE_CEILING[1]
    return STATE_CEILING[number]


class JourneyEvent(models.TextChoices):
    """The events that drive transitions. ``advance(subject, event)`` validates these."""

    # ── v4.0 events (carried forward unchanged) ──────────────────────────────
    PROMPT = "prompt", "Prompt submitted"
    QUALIFY = "qualify", "Qualification completed"
    REVEAL_CLIENT_PAGE = "reveal_client_page", "Client page revealed"
    GATE_INVITE = "gate_invite", "Account invite gate passed"
    GATE_DORMANT = "gate_dormant", "Did not pass invite gate"
    ACCEPT_INVITE = "accept_invite", "Invite accepted (client created)"
    ENGAGE = "engage", "NDA / evaluation started"
    REACTIVATE = "reactivate", "Returned with a stronger signal"

    # ── v6.0 events ──────────────────────────────────────────────────────────
    # Conversation-driven entry points (Backend v6.0 §3.4): a turn posted on an empty
    # thread starts the review; the deterministic stop rule closing the qualification
    # band triggers artifact generation.
    FIRST_TURN = "first_turn", "First turn posted on an empty thread"
    LOOP_CLOSED = "loop_closed", "Question loop closed for the qualification band"
    # Lifecycle events that used to be lumped into ENGAGE.
    NDA_SIGNED = "nda_signed", "NDA signed"
    FIRST_PAYMENT = "first_payment", "First payment recorded"
    POC_START = "poc_start", "PoC started"
    INTEGRATION_START = "integration_start", "Integration started"
    CONTRACT_EXECUTED = "contract_executed", "Contract executed"


class RevealSurface(models.TextChoices):
    """The six gated reveals (Architecture v2.6 §11.5)."""

    CLIENT_PAGE = "client_page", "1 Client page"
    ACCOUNT_INVITE = "account_invite", "2 Account creation"
    PORTAL = "portal", "3 Client portal"
    DATA_ROOM = "data_room", "4 NDA data room"
    SUCCESS_OVERLAY = "success_overlay", "5 Success overlay"
    CUSTOMER_SUCCESS_HOME = "customer_success_home", "6 Customer-success home"


# ─────────────────────────────────────────────────────────────────────────────
# The authoritative transition table: {from_state: {event: to_state}}
# ─────────────────────────────────────────────────────────────────────────────
ALLOWED_TRANSITIONS: dict[str, dict[str, str]] = {
    JourneyState.ARRIVED.value: {
        # A turn posted on an empty thread starts the review (1 → 2).
        JourneyEvent.FIRST_TURN.value: JourneyState.IN_REVIEW.value,
        JourneyEvent.PROMPT.value: JourneyState.IN_REVIEW.value,
        # Tolerate a direct qualify (a scripted/seeded lead that skips the loop).
        JourneyEvent.QUALIFY.value: JourneyState.DIAGNOSED.value,
        JourneyEvent.LOOP_CLOSED.value: JourneyState.DIAGNOSED.value,
    },
    JourneyState.IN_REVIEW.value: {
        # The stop rule fired for the qualification band (2 → 3, then reflection).
        JourneyEvent.LOOP_CLOSED.value: JourneyState.DIAGNOSED.value,
        JourneyEvent.QUALIFY.value: JourneyState.DIAGNOSED.value,
    },
    JourneyState.DIAGNOSED.value: {
        JourneyEvent.REVEAL_CLIENT_PAGE.value: JourneyState.CLIENT_PAGE.value,
    },
    JourneyState.CLIENT_PAGE.value: {
        JourneyEvent.GATE_INVITE.value: JourneyState.INVITED.value,
        JourneyEvent.GATE_DORMANT.value: JourneyState.DORMANT.value,
    },
    JourneyState.INVITED.value: {
        JourneyEvent.ACCEPT_INVITE.value: JourneyState.NDA_REVIEW.value,
        JourneyEvent.GATE_DORMANT.value: JourneyState.DORMANT.value,
    },
    JourneyState.NDA_REVIEW.value: {
        # NDA_SIGNED raises the ceiling (reveal 4) but does NOT move the state — the
        # subject stays in NDA_REVIEW until a payment is recorded. Modelled as a
        # self-transition so it is still audited in JourneyTransition.
        JourneyEvent.NDA_SIGNED.value: JourneyState.NDA_REVIEW.value,
        # First payment activates customer success and moves to the paid Assessment.
        JourneyEvent.FIRST_PAYMENT.value: JourneyState.ASSESSMENT.value,
        # Backward-compatible alias for the v4.0 "engage" event.
        JourneyEvent.ENGAGE.value: JourneyState.ASSESSMENT.value,
        JourneyEvent.GATE_DORMANT.value: JourneyState.DORMANT.value,
    },
    JourneyState.ASSESSMENT.value: {
        JourneyEvent.POC_START.value: JourneyState.POC.value,
        JourneyEvent.GATE_DORMANT.value: JourneyState.DORMANT.value,
    },
    JourneyState.POC.value: {
        JourneyEvent.INTEGRATION_START.value: JourneyState.INTEGRATION.value,
        JourneyEvent.GATE_DORMANT.value: JourneyState.DORMANT.value,
    },
    JourneyState.INTEGRATION.value: {
        JourneyEvent.CONTRACT_EXECUTED.value: JourneyState.CUSTOMER_SUCCESS.value,
        JourneyEvent.GATE_DORMANT.value: JourneyState.DORMANT.value,
    },
    JourneyState.CUSTOMER_SUCCESS.value: {
        # Terminal on the ladder. Expansion is a commercial motion INSIDE State 10, not
        # a journey transition — it must never silently move the customer.
    },
    JourneyState.DORMANT.value: {
        JourneyEvent.REACTIVATE.value: JourneyState.CLIENT_PAGE.value,
    }
}


# Which reveal (if any) a resulting state unlocks.
STATE_REVEAL: dict[str, str] = {
    JourneyState.CLIENT_PAGE.value: RevealSurface.CLIENT_PAGE.value,
    JourneyState.INVITED.value: RevealSurface.ACCOUNT_INVITE.value,
    JourneyState.NDA_REVIEW.value: RevealSurface.PORTAL.value,
    JourneyState.ASSESSMENT.value: RevealSurface.SUCCESS_OVERLAY.value,
    JourneyState.CUSTOMER_SUCCESS.value: RevealSurface.CUSTOMER_SUCCESS_HOME.value,
}

# Reveal 4 (the NDA data room) is fired by an EVENT rather than by arriving at a state,
# because the NDA can be signed at any point inside NDA_REVIEW.
EVENT_REVEAL: dict[str, str] = {
    JourneyEvent.NDA_SIGNED.value: RevealSurface.DATA_ROOM.value,
}


class JourneyTransition(BaseModel):
    """
    An append-only record of one state transition, for audit + timeline.

    ``lead`` is the subject. We keep the raw from/to/event plus an optional actor and a
    free-form ``meta`` blob (gate inputs, agent run ids, thread ids, etc.).
    """

    lead = models.ForeignKey(
        "leads.Lead",
        on_delete=models.CASCADE,
        related_name="journey_transitions",
    )
    from_state = models.CharField(max_length=20, choices=JourneyState.choices)
    to_state = models.CharField(max_length=20, choices=JourneyState.choices)
    event = models.CharField(max_length=32, choices=JourneyEvent.choices)
    reveal = models.CharField(
        max_length=24, choices=RevealSurface.choices, blank=True, default=""
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="journey_transitions",
    )
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Journey transition"
        verbose_name_plural = "Journey transitions"
        indexes = [
            models.Index(fields=["lead", "to_state"]),
            models.Index(fields=["to_state", "created_at"]),
        ]

    def __str__(self) -> str:
        return (
            f"JourneyTransition({self.lead_id}: "
            f"{self.from_state}->{self.to_state} on {self.event})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# The v6.0 artifact registry
# ─────────────────────────────────────────────────────────────────────────────
# Artifact / QuestionSuggestion / CoverageSnapshot live in ``models_artifacts.py`` for
# review clarity but MUST be imported here so Django registers them under the
# ``journey`` app label.
from apps.journey.models_artifacts import (  # noqa: E402,F401  (re-export)
    Artifact,
    CoverageSnapshot,
    QuestionSuggestion,
)
