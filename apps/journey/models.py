"""
Journey models.

The progressive-disclosure state machine (Backend v4 §3.2). A single explicit
``JourneyState`` governs which surface a subject (a Lead, later mirrored to a Client)
may see, and drives the four timed reveals. State lives on the Lead; this app owns the
enum, the reveal-surface vocabulary, and the append-only transition log.

Nothing here mutates a Lead directly — transitions go through
``apps.journey.services.advance.advance()``, which validates the transition, records a
``JourneyTransition`` row, and triggers downstream fan-out. Views must never set state
directly.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class JourneyState(models.TextChoices):
    """
    The nine journey states (Backend v4 §3.2).

        ARRIVED ──prompt──▶ IN_REVIEW ──qualify──▶ DIAGNOSED
                                                     │ (reveal ① client page)
                                                     ▼
                                               CLIENT_PAGE
                                          ┌────────┴─────────┐
                             gate=true    │                  │  gate=false
                          (reveal ②)      ▼                  ▼
                                       INVITED           DORMANT ◀─┐ returns w/
                                          │ accept                 │ stronger signal
                             (reveal ③)   ▼                        │
                                       CLIENT ──nda/eval──▶ ENGAGED│ (reveal ④ data room)
                                          └─────────────────────────┘
    """

    ARRIVED = "ARRIVED", "Arrived"
    IN_REVIEW = "IN_REVIEW", "In review"
    DIAGNOSED = "DIAGNOSED", "Diagnosed"
    CLIENT_PAGE = "CLIENT_PAGE", "Client page"
    INVITED = "INVITED", "Invited"
    CLIENT = "CLIENT", "Client"
    ENGAGED = "ENGAGED", "Engaged"
    DORMANT = "DORMANT", "Dormant"


class JourneyEvent(models.TextChoices):
    """The events that drive transitions. ``advance(subject, event)`` validates these."""

    PROMPT = "prompt", "Prompt submitted"
    QUALIFY = "qualify", "Qualification completed"
    REVEAL_CLIENT_PAGE = "reveal_client_page", "Client page revealed"
    GATE_INVITE = "gate_invite", "Account invite gate passed"
    GATE_DORMANT = "gate_dormant", "Did not pass invite gate"
    ACCEPT_INVITE = "accept_invite", "Invite accepted (client created)"
    ENGAGE = "engage", "NDA / evaluation started"
    REACTIVATE = "reactivate", "Returned with a stronger signal"


class RevealSurface(models.TextChoices):
    """The surfaces a capability token may grant reach to (reveals ①–④)."""

    CLIENT_PAGE = "client_page", "Client page"
    ACCOUNT_INVITE = "account_invite", "Account invite"
    PORTAL = "portal", "Portal"
    DATA_ROOM = "data_room", "Data room"


# The authoritative transition table: {from_state: {event: to_state}}.
ALLOWED_TRANSITIONS: dict[str, dict[str, str]] = {
    JourneyState.ARRIVED: {
        JourneyEvent.PROMPT: JourneyState.IN_REVIEW,
        JourneyEvent.QUALIFY: JourneyState.DIAGNOSED,  # tolerate a direct qualify
    },
    JourneyState.IN_REVIEW: {
        JourneyEvent.QUALIFY: JourneyState.DIAGNOSED,
    },
    JourneyState.DIAGNOSED: {
        JourneyEvent.REVEAL_CLIENT_PAGE: JourneyState.CLIENT_PAGE,
    },
    JourneyState.CLIENT_PAGE: {
        JourneyEvent.GATE_INVITE: JourneyState.INVITED,
        JourneyEvent.GATE_DORMANT: JourneyState.DORMANT,
    },
    JourneyState.INVITED: {
        JourneyEvent.ACCEPT_INVITE: JourneyState.CLIENT,
        JourneyEvent.GATE_DORMANT: JourneyState.DORMANT,
    },
    JourneyState.CLIENT: {
        JourneyEvent.ENGAGE: JourneyState.ENGAGED,
        JourneyEvent.GATE_DORMANT: JourneyState.DORMANT,
    },
    JourneyState.ENGAGED: {},  # terminal-ish; further movement is lifecycle, not journey
    JourneyState.DORMANT: {
        JourneyEvent.REACTIVATE: JourneyState.CLIENT_PAGE,
    },
}

# Which reveal (if any) a resulting state unlocks.
STATE_REVEAL: dict[str, str] = {
    JourneyState.CLIENT_PAGE: RevealSurface.CLIENT_PAGE,
    JourneyState.INVITED: RevealSurface.ACCOUNT_INVITE,
    JourneyState.CLIENT: RevealSurface.PORTAL,
    JourneyState.ENGAGED: RevealSurface.DATA_ROOM,
}


class JourneyTransition(BaseModel):
    """
    An append-only record of one state transition, for audit + timeline.

    ``lead`` is the subject. We keep the raw from/to/event plus an optional actor and a
    free-form ``meta`` blob (gate inputs, agent run ids, etc.).
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
        max_length=20, choices=RevealSurface.choices, blank=True, default=""
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
        return f"JourneyTransition({self.lead_id}: {self.from_state}→{self.to_state} on {self.event})"
