"""
Inline-card assembly (Backend v6.0 §Phase 3, Architecture v2.6 §5).

    Commitment asks render as INLINE CARDS rather than page CTAs.

Seven card kinds: NBA, disclosure boundary, specialist, scheduling, relationship team,
support, feedback.

── THE COMMITMENT GATE IS APPLIED AT THE PAYLOAD ────────────────────────────
This is the single most important line in the module. §5 and the Phase-2 note in
``gate.commitment_allowed`` both say it:

    A commitment card present in a payload where ``value_delivered`` is false is A DEFECT.

The gate is enforced HERE, when the card is built — not by the frontend declining to
render it. A frontend-side gate means the card was on the wire, and anything on the wire
can be read: by a proxy, by a devtools panel, by a screenshot, by the next refactor that
forgets to check.

── A CARD IS NOT A NAVIGATION ───────────────────────────────────────────────
Cards append to the transcript. ``href`` is optional and is an ALTERNATIVE view (for
emailing, sharing or printing), never the primary one. A frontend that responds to a card
by routing is a defect (§11.9).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("itrix")

# The closed card vocabulary. An unknown kind is a server error for the same reason an
# unknown sidebar section is: a generic renderer would display a payload nobody designed
# a disclosure review for.
CARD_NBA = "nba"
CARD_DISCLOSURE_BOUNDARY = "disclosure_boundary"
CARD_SPECIALIST = "specialist"
CARD_SCHEDULING = "scheduling"
CARD_RELATIONSHIP_TEAM = "relationship_team"
CARD_SUPPORT = "support"
CARD_FEEDBACK = "feedback"

CARD_KINDS: frozenset[str] = frozenset({
    CARD_NBA, CARD_DISCLOSURE_BOUNDARY, CARD_SPECIALIST, CARD_SCHEDULING,
    CARD_RELATIONSHIP_TEAM, CARD_SUPPORT, CARD_FEEDBACK,
})

# Cards that constitute a COMMITMENT ASK and are therefore gated on value delivery.
COMMITMENT_CARDS: frozenset[str] = frozenset({CARD_SCHEDULING, CARD_SPECIALIST})

# Which commitment ask each gated card represents, for ``gate.commitment_allowed``.
_CARD_ASK = {
    CARD_SCHEDULING: "concierge_handoff",
    CARD_SPECIALIST: "concierge_handoff",
}


class UnknownCardKind(Exception):
    """Raised when a card kind is outside the closed vocabulary."""


@dataclass
class Card:
    """One inline card."""

    kind: str
    title: str
    body: str = ""
    actions: list[dict] = field(default_factory=list)
    # An ALTERNATIVE view, never the primary one.
    href: str | None = None
    dismissible: bool = True

    def __post_init__(self):
        if self.kind not in CARD_KINDS:
            raise UnknownCardKind(
                f"Unknown card kind {self.kind!r}. Allowed: {sorted(CARD_KINDS)}"
            )

    def to_payload(self) -> dict:
        return {
            "kind": self.kind,
            "title": self.title,
            "body": self.body,
            "actions": self.actions,
            "href": self.href,
            "dismissible": self.dismissible,
        }


def _commitment_permitted(subject, kind: str) -> bool:
    """
    Whether this commitment card may be built at all.

    Value must precede the ask. Returns False on any error — a gate that fails open is
    not a gate.
    """
    if kind not in COMMITMENT_CARDS:
        return True
    if subject is None:
        return False
    try:
        from apps.journey.services.gate import commitment_allowed

        return bool(commitment_allowed(subject, _CARD_ASK.get(kind, "concierge_handoff")))
    except Exception:  # noqa: BLE001
        logger.exception("commitment gate unavailable; refusing the card")
        return False


def build(subject, *, thread=None, client=None, decision=None) -> list[dict]:
    """
    Assemble every card the subject is currently entitled to.

    Returns payload dicts, gated. The caller appends them to the transcript; it does not
    re-check anything, because everything checkable was checked here.
    """
    cards: list[Card] = []

    nba_card = build_nba_card(subject, client=client, decision=decision)
    if nba_card is not None:
        cards.append(nba_card)

    boundary = build_disclosure_boundary_card(subject)
    if boundary is not None:
        cards.append(boundary)

    for builder in (
        build_relationship_team_card,
        build_support_card,
        build_feedback_card,
    ):
        card = builder(client or _client_for(subject))
        if card is not None:
            cards.append(card)

    for builder in (build_specialist_card, build_scheduling_card):
        card = builder(subject)
        if card is not None:
            cards.append(card)

    return [card.to_payload() for card in cards]


# ─────────────────────────────────────────────────────────────────────────────
# Card builders
# ─────────────────────────────────────────────────────────────────────────────
def build_nba_card(subject, *, client=None, decision=None) -> Card | None:
    """
    The next-best-action card.

    Passes through ``nba_precedence`` so the portal and the cockpit cannot disagree
    (§11.1). The suppression reason is NOT carried into the card — it is internal.
    """
    from apps.governance.services import nba_precedence

    if decision is None:
        resolved_client = client or _client_for(subject)
        decision = nba_precedence.next_best_action(resolved_client, _candidates_for(subject))

    payload = decision.to_client_payload()
    if not payload:
        return None

    # A commercial primary that survived the rule is still gated on value delivery.
    if decision.primary is not None and decision.primary.commercial:
        if not _commitment_permitted(subject, CARD_SCHEDULING):
            return None

    return Card(
        kind=CARD_NBA,
        title=payload["label"],
        body=payload.get("detail", "") or "",
        actions=[{"key": payload["key"], "label": payload["label"]}],
        href=payload.get("href"),
    )


def build_disclosure_boundary_card(subject) -> Card | None:
    """
    The disclosure-boundary card (Playbook §13.2).

    Names WHAT WOULD BECOME AVAILABLE and WHAT IT WOULD REQUIRE — never what is being
    withheld. "We are not showing you X" tells the visitor that X exists; the approved
    framing describes the next step instead.
    """
    from apps.journey.models import journey_number

    number = journey_number(getattr(subject, "journey_state", None))
    if number is None or number >= 6:
        # From NDA_REVIEW onward the boundary has already been crossed.
        return None
    if getattr(subject, "value_delivered_at", None) is None:
        # Before value, a boundary card is a commitment ask wearing a disguise.
        return None

    return Card(
        kind=CARD_DISCLOSURE_BOUNDARY,
        title="What we can look at together next",
        body=(
            "We can go a long way on non-confidential descriptions of your workload. "
            "An NDA would let us look at its actual structure and be specific about "
            "where the boundary cost sits."
        ),
        actions=[{"key": "nda_info", "label": "What an NDA would cover"}],
    )


def build_specialist_card(subject) -> Card | None:
    """
    "Bring in a specialist" — a COMMITMENT ASK, gated.

    R30 means a named human is always reachable; this card is the PROACTIVE offer, which
    is a different thing and is correctly gated on value having been delivered.
    """
    if not _commitment_permitted(subject, CARD_SPECIALIST):
        return None
    return Card(
        kind=CARD_SPECIALIST,
        title="Bring in a specialist",
        body="Someone who works on this every day can look at it with you.",
        actions=[{"key": "request_specialist", "label": "Ask for a specialist"}],
    )


def build_scheduling_card(subject) -> Card | None:
    """A scheduling ask — a COMMITMENT ASK, gated."""
    if not _commitment_permitted(subject, CARD_SCHEDULING):
        return None
    return Card(
        kind=CARD_SCHEDULING,
        title="Book a compute bottleneck review",
        body="A working session on one representative workload.",
        actions=[{"key": "book_review", "label": "Find a time"}],
    )


def build_relationship_team_card(client) -> Card | None:
    """
    The named humans (§12H).

    NOT a commitment ask, and therefore NOT gated: R30 is an absolute — a customer can
    always reach a named human WITHOUT first negotiating with an agent. Gating this card
    would be the negotiation.
    """
    if client is None:
        return None
    try:
        from apps.customer_success.models import RelationshipTeamMember

        members = list(RelationshipTeamMember.objects.filter(client=client)[:4])
    except Exception:  # noqa: BLE001
        return None
    if not members:
        return None

    return Card(
        kind=CARD_RELATIONSHIP_TEAM,
        title="Your team at itriX",
        body="You can reach any of them directly.",
        actions=[
            {"key": f"contact_{m.role}", "label": f"{m.display_name} — {m.get_role_display()}"}
            for m in members
        ],
        dismissible=False,
    )


def build_support_card(client) -> Card | None:
    """An open support request, surfaced in-thread. Never gated."""
    if client is None:
        return None
    try:
        from apps.customer_success.models import SupportRequest

        open_count = SupportRequest.objects.filter(
            client=client, resolved_at__isnull=True
        ).count()
    except Exception:  # noqa: BLE001
        return None
    if not open_count:
        return None

    return Card(
        kind=CARD_SUPPORT,
        title=f"{open_count} open support request{'s' if open_count != 1 else ''}",
        body="Who owns each one, and when you can expect a response.",
        actions=[{"key": "view_support", "label": "See your requests"}],
        dismissible=False,
    )


def build_feedback_card(client) -> Card | None:
    """
    The private pulse (§12I). Never gated, and never carries a score.

    The card's body IS the privacy promise, so it is stated on the card rather than
    somewhere the customer has to go looking for it.
    """
    if client is None:
        return None
    if not getattr(client, "first_payment_recorded_at", None):
        return None
    try:
        from apps.customer_success.services import feedback_pulse

        prompt = feedback_pulse.PROMPT
    except Exception:  # noqa: BLE001
        return None

    return Card(
        kind=CARD_FEEDBACK,
        title="How are we doing?",
        body=prompt,
        actions=[{"key": "submit_feedback", "label": "Share privately"}],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _client_for(subject):
    if subject is None:
        return None
    client = getattr(subject, "client", None)
    if client is not None:
        return client
    try:
        from apps.clients.models import Client

        return Client.objects.filter(lead=subject).first()
    except Exception:  # noqa: BLE001
        return None


def _candidates_for(subject):
    """
    Build the candidate list for this subject.

    Delegates to the Strategy agent, which is where candidates are actually produced.
    Returns an empty list rather than raising — no candidates means no card, which is a
    valid outcome.
    """
    try:
        from apps.agents.services.strategy import nba_candidates

        return nba_candidates(subject)
    except Exception:  # noqa: BLE001
        logger.debug("no NBA candidates available for subject %s", getattr(subject, "id", "?"))
        return []
