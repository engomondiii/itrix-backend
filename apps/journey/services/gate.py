"""
Deterministic journey gates (Backend v4 §3.3).

No LLM, fully auditable. Two questions:

  * ``account_invite_allowed(lead)``  — reveal ② logic: is this lead a strong enough
    fit to be invited into a private workspace?
  * ``commitment_allowed(lead, ask)`` — value-first enforcement: a commitment ask is
    only ever reached AFTER value has been delivered (``lead.value_delivered_at``).

Thresholds live here as constants that the team can tune; every gate DECISION is
written to ``LeadActivity`` (via ``record_gate_decision``) for audit.
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


def account_invite_allowed(lead) -> bool:
    """Reveal ② gate — deterministic, auditable, no LLM."""
    if getattr(lead, "tier", 4) in _INVITE_TIERS:
        return True
    strong_intent = getattr(lead, "commercial_intent", "") in _STRONG_INTENT
    special = getattr(lead, "special_rights", "None") not in ("None", "", None)
    return bool(strong_intent or special)


def commitment_allowed(lead, ask: str) -> bool:
    """
    Value-first enforcement. A commitment ask is only allowed once the lead has
    received value (``value_delivered_at`` is set). ``account_creation`` additionally
    requires the invite gate.
    """
    if ask not in COMMITMENT_ASKS:
        # Unknown asks are refused rather than silently allowed.
        return False
    if getattr(lead, "value_delivered_at", None) is None:
        return False  # value MUST precede the ask
    if ask == "account_creation":
        return account_invite_allowed(lead)
    return True


def record_gate_decision(lead, *, ask: str, allowed: bool, reason: str = "") -> None:
    """
    Write the gate decision to the lead audit trail (LeadActivity) and stamp the
    lead's ``gate_decision`` audit fields. Best-effort — never raises.
    """
    try:
        from apps.leads.models import LeadActivity

        LeadActivity.objects.create(
            lead=lead,
            type=LeadActivity.ActivityType.STATUS_CHANGE,
            label=f"Gate '{ask}': {'allowed' if allowed else 'denied'}"
            + (f" — {reason}" if reason else ""),
            meta={"gate": ask, "allowed": allowed, "reason": reason},
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to record gate decision for lead %s", getattr(lead, "id", "?"))

    # Stamp the lead's lightweight audit fields (added in Phase 1 to leads.models).
    try:
        lead.gate_decision = "allowed" if allowed else "denied"
        lead.gate_decision_reason = reason
        lead.save(update_fields=["gate_decision", "gate_decision_reason", "updated_at"])
    except Exception:  # noqa: BLE001
        # The fields may not exist in older migrations mid-migration; ignore.
        pass
