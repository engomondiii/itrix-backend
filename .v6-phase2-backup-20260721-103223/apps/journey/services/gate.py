"""
Deterministic journey gates (Backend v6.0 §3.1, §5.3).

NO LLM, fully auditable. This is Layer 1 — and Layer 1 staying deterministic is the
reason the whole system can be trusted to terminate and to disclose correctly. The
language model chooses the WORDING of a question; it never decides whether a subject
qualifies, what state they are in, or what may be disclosed to them.

Five questions:

  * ``account_invite_allowed(lead)``   — reveal 2: is this lead a strong enough fit to be
    invited into a private workspace?
  * ``commitment_allowed(lead, ask)``  — value-first: a commitment ask is only ever
    reachable AFTER value has been delivered (``lead.value_delivered_at``).
  * ``success_overlay_allowed(lead)``  — reveal 5: customer-success modules activate at
    the FIRST PAYMENT, not at license-out.
  * ``expansion_allowed(lead)``        — may a COMMERCIAL next-best-action be offered at
    all? Customer health outranks pipeline.
  * ``question_loop_open(lead)``       — v6.0: should the adaptive question loop keep
    asking, or has the deterministic stop rule fired?

Every gate DECISION is written to ``LeadActivity`` (via ``record_gate_decision``) for
audit. Thresholds live here as constants the team can tune.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("itrix")

# Tiers that always earn a workspace invite.
_INVITE_TIERS = {1, 2}

# Commercial-intent signals strong enough to earn an invite regardless of tier.
_STRONG_INTENT = {
    "confidential_evaluation",
    "paid_assessment",
    "paid_poc",
    "sdk_runtime_integration",
    "field_licensing",
    "strategic_investment",
    "acquisition_partnership",
}

# The five commitment asks (value must precede each).
COMMITMENT_ASKS = {"account_creation", "nda", "paid_evaluation", "poc", "concierge_handoff"}

# The qualification band — the states in which the adaptive question loop runs.
# Once the subject passes State 3 the reflection has been delivered and the loop for
# the qualification band is closed by definition.
QUALIFICATION_BAND_STATES = {"ARRIVED", "IN_REVIEW"}


def account_invite_allowed(lead) -> bool:
    """Reveal 2 gate — deterministic, auditable, no LLM."""
    if getattr(lead, "tier", 4) in _INVITE_TIERS:
        return True
    strong_intent = getattr(lead, "commercial_intent", "") in _STRONG_INTENT
    special = getattr(lead, "special_rights", "None") not in ("None", "", None)
    return bool(strong_intent or special)


def commitment_allowed(lead, ask: str) -> bool:
    """
    Value-first enforcement. A commitment ask is only allowed once the lead has received
    value (``value_delivered_at`` is set). ``account_creation`` additionally requires the
    invite gate.

    v6.0 note: commitment asks now render as INLINE CARDS rather than page CTAs, so this
    gate is enforced on the card payload at the serializer — not by the frontend
    declining to render (Architecture v2.6 §5). A commitment card present in a payload
    where ``value_delivered`` is false is a defect.
    """
    if ask not in COMMITMENT_ASKS:
        # Unknown asks are refused rather than silently allowed.
        return False
    if getattr(lead, "value_delivered_at", None) is None:
        return False  # value MUST precede the ask
    if ask == "account_creation":
        return account_invite_allowed(lead)
    return True


def success_overlay_allowed(lead) -> bool:
    """
    Reveal 5 gate — the customer-success overlay.

    THE RULE THAT MATTERS: customer-success modules activate at the FIRST PAYMENT, not
    at license-out (Architecture v2.6 §7.1, R16). A paid Assessment customer already has
    named owners, support access and success goals.

    So this is true from State 7 (ASSESSMENT) onward, or as soon as a first payment is
    recorded on the client — whichever comes first.
    """
    from apps.journey.models import journey_number

    number = journey_number(getattr(lead, "journey_state", None))
    if number is not None and number >= 7:
        return True

    client = _client_for(lead)
    if client is not None and getattr(client, "first_payment_recorded_at", None):
        return True
    return False


def expansion_allowed(lead) -> bool:
    """
    May a COMMERCIAL next-best-action be ranked primary?

    This is the customer-first guardrail in gate form (Architecture v2.6 §18.7). The
    full five-step precedence rule lands in Phase 3 (``governance/services/nba_precedence``);
    this gate answers the coarser question the shell contract needs: is expansion even
    eligible right now?

    Expansion requires ALL of:
      * the subject has reached a paid state (7+), AND
      * no blocking support issue is open, AND
      * customer health is not degraded.

    A commercial candidate ranked primary while any of these fail is a DEFECT, not a
    judgement call. Phase 1 answers conservatively: when the customer-success domain is
    not yet deployed (Phase 2), the health/support signals are unknown, and unknown
    health means NO expansion.
    """
    from apps.journey.models import journey_number

    number = journey_number(getattr(lead, "journey_state", None))
    if number is None or number < 7:
        return False

    client = _client_for(lead)
    if client is None:
        return False

    # Health signals arrive with the Phase-2 customer-success domain. Until then the
    # honest answer is "unknown", and unknown must not authorize a sales motion.
    health = getattr(client, "customer_health", None)
    if health is None:
        return False
    if str(health).lower() in {"at_risk", "critical", "degraded", "off_plan"}:
        return False

    if _has_blocking_support_issue(client):
        return False
    return True


def question_loop_open(lead) -> bool:
    """
    v6.0: is the adaptive question loop still open for this subject?

    A DERIVED boolean (Architecture v2.6 §11.4). True while the coverage tracker reports
    uncovered required dimensions AND the per-state budget is not exhausted AND no
    hand-off signal has fired. When it goes false for the qualification band, artifact
    generation is triggered.

    ── PHASE 1 SCOPE ────────────────────────────────────────────────────────
    The coverage tracker, the stop rule and the question generator all land in Phase 2
    (``apps/agents/services/coverage.py``, ``stop_rule.py``, ``question_generator.py``).
    Phase 1 must still emit a correct ``question_loop_open`` in the shell contract, so
    it answers from what IS deterministic today:

        * open  while the subject is inside the qualification band (states 1-2)
        * closed once the reflection has been delivered (state 3+) or the subject is
          DORMANT.

    When ENABLE_ADAPTIVE_QUESTIONS is on and the Phase-2 stop rule is importable, this
    delegates to it — so Phase 2 needs no change here.
    """
    from django.conf import settings

    from apps.journey.models import normalize_state

    state = normalize_state(getattr(lead, "journey_state", None))

    if getattr(settings, "ENABLE_ADAPTIVE_QUESTIONS", False):
        try:
            from apps.agents.services.stop_rule import loop_should_continue

            return bool(loop_should_continue(lead))
        except Exception:  # noqa: BLE001 - Phase 2 not deployed yet
            logger.debug("stop_rule unavailable; falling back to band check")

    return state in QUALIFICATION_BAND_STATES


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _client_for(lead):
    """Resolve the Client for a lead, tolerating the app being unavailable."""
    client = getattr(lead, "client", None)
    if client is not None:
        return client
    try:
        from apps.clients.models import Client

        return Client.objects.filter(lead=lead).first()
    except Exception:  # noqa: BLE001
        return None


def _has_blocking_support_issue(client) -> bool:
    """
    True when a blocking support request is open (Phase 2 domain).

    Conservative default: if we cannot tell, we do NOT claim the customer is fine — but
    we also do not invent a blocking issue. ``expansion_allowed`` already refuses when
    health is unknown, so returning False here cannot authorize a sale on its own.
    """
    try:
        from apps.customer_success.models import SupportRequest

        return SupportRequest.objects.filter(
            client=client, blocking=True, resolved_at__isnull=True
        ).exists()
    except Exception:  # noqa: BLE001 - customer_success arrives in Phase 2
        return False


def record_gate_decision(lead, *, ask: str, allowed: bool, reason: str = "") -> None:
    """
    Write the gate decision to the lead audit trail (LeadActivity) and stamp the lead's
    ``gate_decision`` audit fields. Best-effort — never raises.
    """
    try:
        from apps.leads.models import LeadActivity

        LeadActivity.objects.create(
            lead=lead,
            type=LeadActivity.ActivityType.STATUS_CHANGE,
            label=f"Gate '{ask}': {'allowed' if allowed else 'denied'}"
            + (f" - {reason}" if reason else ""),
            meta={"gate": ask, "allowed": allowed, "reason": reason},
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to record gate decision for lead %s", getattr(lead, "id", "?"))

    try:
        lead.gate_decision = "allowed" if allowed else "denied"
        lead.gate_decision_reason = reason
        lead.save(update_fields=["gate_decision", "gate_decision_reason", "updated_at"])
    except Exception:  # noqa: BLE001
        # The fields may not exist mid-migration; ignore.
        pass
