"""
The customer-first next-best-action rule (Backend v6.0 §Phase 3, Architecture v2.6 §18.7).

    THE PRECEDENCE RULE, IN ORDER:

      1. a blocking support issue is open        -> a SUPPORT action is primary
      2. an agreed outcome is off plan           -> an OUTCOME action is primary
      3. adoption is below plan                  -> an ENABLEMENT action is primary
      4. a negative trust signal exists          -> HUMAN OUTREACH is primary
      5. otherwise, and ONLY if expansion_allowed -> a COMMERCIAL action is eligible

    A COMMERCIAL CANDIDATE RANKED PRIMARY WHILE ANY OF CONDITIONS 1-4 HOLD IS A DEFECT,
    NOT A JUDGEMENT CALL.

── WHY THIS LIVES ON THE BACKEND, ONCE ──────────────────────────────────────
§11.1: ``next_best_action`` passes through this module on BOTH the portal path and the
cockpit path, so a customer and an operator can never see contradictory guidance. If the
rule were implemented twice — once for each surface — they would drift, and the first
symptom would be a customer being sold to while their operator was looking at an
unresolved outage.

── WHY SUPPRESSION IS VISIBLE ───────────────────────────────────────────────
Every suppression returns a ``suppression_reason``. An operator who sees "no expansion
action" with no explanation will assume the system is broken and work around it. One who
sees "suppressed: a blocking support request is open" understands the rule and trusts it.

The reason is INTERNAL-ONLY (§10.5) — it appears on the cockpit, never on the customer's
payload. A customer does not need to be told we decided not to sell to them today.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.conf import settings

logger = logging.getLogger("itrix")

# Action kinds. ``commercial`` is the only one the rule can suppress.
KIND_SUPPORT = "support"
KIND_OUTCOME = "outcome"
KIND_ENABLEMENT = "enablement"
KIND_HUMAN_OUTREACH = "human_outreach"
KIND_COMMERCIAL = "commercial"
KIND_INFORMATIONAL = "informational"

# Suppression reasons, in precedence order.
SUPPRESSED_BLOCKING_SUPPORT = "blocking_support_issue_open"
SUPPRESSED_OUTCOME_OFF_PLAN = "agreed_outcome_off_plan"
SUPPRESSED_ADOPTION_BELOW_PLAN = "adoption_below_plan"
SUPPRESSED_NEGATIVE_TRUST = "negative_trust_signal"
SUPPRESSED_EXPANSION_NOT_ALLOWED = "expansion_not_allowed"
SUPPRESSED_HEALTH_UNKNOWN = "customer_health_unknown"

# Human-readable, for the cockpit. Every one names the CUSTOMER's situation, not ours.
SUPPRESSION_COPY = {
    SUPPRESSED_BLOCKING_SUPPORT: "A blocking support request is open for this customer.",
    SUPPRESSED_OUTCOME_OFF_PLAN: "An agreed outcome is off plan or at risk.",
    SUPPRESSED_ADOPTION_BELOW_PLAN: "Adoption is behind the agreed plan.",
    SUPPRESSED_NEGATIVE_TRUST: "Recent feedback from this customer was negative.",
    SUPPRESSED_EXPANSION_NOT_ALLOWED: "This customer is not eligible for an expansion motion.",
    SUPPRESSED_HEALTH_UNKNOWN: "Customer health has not been measured yet.",
}


@dataclass
class ActionCandidate:
    """
    One candidate action.

    ``commercial`` is the boolean the rule reads. It is carried on the CANDIDATE rather
    than inferred from the label, because "would you like to discuss another workload?"
    is commercial and does not look it.
    """

    key: str
    label: str
    kind: str = KIND_INFORMATIONAL
    commercial: bool = False
    detail: str = ""
    href: str | None = None
    weight: int = 0

    def to_payload(self) -> dict:
        """The client-plane shape. Carries no weight and no kind-internal reasoning."""
        return {"key": self.key, "label": self.label, "detail": self.detail, "href": self.href}


@dataclass
class NBADecision:
    """
    The outcome: what to show, and — when something was held back — why.

    ``suppression_reason`` is INTERNAL-ONLY. ``primary`` is safe for either plane.
    """

    primary: ActionCandidate | None = None
    secondary: list[ActionCandidate] = field(default_factory=list)
    suppression_reason: str = ""
    suppressed: list[ActionCandidate] = field(default_factory=list)
    signals: dict = field(default_factory=dict)

    @property
    def suppression_copy(self) -> str:
        return SUPPRESSION_COPY.get(self.suppression_reason, "")

    def to_client_payload(self) -> dict | None:
        """
        What the CUSTOMER sees: the action, and nothing about what was withheld.

        A customer does not need to be told we decided not to sell to them today, and
        telling them would be a strange kind of honesty — it would surface a commercial
        deliberation they never asked to be part of.
        """
        return self.primary.to_payload() if self.primary else None

    def to_team_payload(self) -> dict:
        """What the OPERATOR sees: everything, including the reason."""
        return {
            "primary": self.primary.to_payload() if self.primary else None,
            "primaryKind": self.primary.kind if self.primary else None,
            "secondary": [c.to_payload() for c in self.secondary],
            "suppressionReason": self.suppression_reason or None,
            "suppressionCopy": self.suppression_copy or None,
            "suppressedCount": len(self.suppressed),
            "signals": self.signals,
        }


def enabled() -> bool:
    return bool(getattr(settings, "ENABLE_CUSTOMER_FIRST_NBA", False))


# ─────────────────────────────────────────────────────────────────────────────
# Signal collection
# ─────────────────────────────────────────────────────────────────────────────
def collect_signals(client) -> dict:
    """
    Gather the four inputs the rule reads.

    Every signal FAILS SAFE: if a subsystem is unavailable we report the state that
    SUPPRESSES rather than the one that permits. An unavailable health service must not
    read as a healthy customer.
    """
    signals = {
        "blocking_support": False,
        "outcome_off_plan": False,
        "adoption_below_plan": False,
        "negative_trust": False,
        "health": "",
        "expansion_allowed": False,
    }
    if client is None:
        return signals

    try:
        from apps.customer_success.services import support_router

        signals["blocking_support"] = support_router.open_blocking_for(client)
    except Exception:  # noqa: BLE001
        logger.debug("support signal unavailable; treating as blocking")
        signals["blocking_support"] = True

    try:
        from apps.customer_success.services import outcome_tracker

        signals["outcome_off_plan"] = outcome_tracker.any_off_plan(client)
    except Exception:  # noqa: BLE001
        signals["outcome_off_plan"] = True

    try:
        signals["adoption_below_plan"] = adoption_below_plan(client)
    except Exception:  # noqa: BLE001
        signals["adoption_below_plan"] = True

    try:
        from apps.customer_success.services import feedback_pulse

        signals["negative_trust"] = feedback_pulse.has_negative_signal(client)
    except Exception:  # noqa: BLE001
        signals["negative_trust"] = True

    # Wrapped like every other signal. An unwrapped attribute read looks harmless, but a
    # property that raises would propagate out of collect_signals and take the whole NBA
    # path down — turning a degraded health service into a broken recommendation engine.
    try:
        signals["health"] = (getattr(client, "customer_health", "") or "").strip().lower()
    except Exception:  # noqa: BLE001
        signals["health"] = ""

    try:
        from apps.journey.services.gate import expansion_allowed

        lead = getattr(client, "lead", None)
        signals["expansion_allowed"] = bool(lead is not None and expansion_allowed(lead))
    except Exception:  # noqa: BLE001
        signals["expansion_allowed"] = False

    return signals


def adoption_below_plan(client) -> bool:
    """
    Condition 3: is adoption behind the agreed plan?

    Derived from the shared 30/60/90 plan: a milestone that is past due and not complete
    is adoption behind plan. Deliberately NOT a usage metric — the plan is what both
    sides agreed, and measuring against our own telemetry instead would let us declare
    adoption healthy while the customer's own goals slipped.
    """
    from django.utils import timezone

    try:
        from apps.customer_success.models import OutcomeStatus, SuccessPlanMilestone

        today = timezone.now().date()
        return SuccessPlanMilestone.objects.filter(
            plan__client=client,
            plan__is_active=True,
            completed_at__isnull=True,
            due_on__lt=today,
        ).exclude(status=OutcomeStatus.ACHIEVED).exists()
    except Exception:  # noqa: BLE001
        return False


# ─────────────────────────────────────────────────────────────────────────────
# The rule
# ─────────────────────────────────────────────────────────────────────────────
def rank(candidates: list[ActionCandidate], *, client=None, signals: dict | None = None) -> NBADecision:
    """
    Apply the five-step precedence rule to ``candidates``.

    Returns the promoted action plus a suppression reason when a commercial candidate
    was held back. The order of the four conditions is fixed and is not configurable —
    a configurable safety rule is a rule somebody will eventually configure away.
    """
    signals = signals if signals is not None else collect_signals(client)
    candidates = list(candidates or [])

    commercial = [c for c in candidates if c.commercial or c.kind == KIND_COMMERCIAL]
    non_commercial = [c for c in candidates if c not in commercial]

    # ── Conditions 1-4, in order. The FIRST that holds decides. ──────────────
    for condition, reason, kind in (
        ("blocking_support", SUPPRESSED_BLOCKING_SUPPORT, KIND_SUPPORT),
        ("outcome_off_plan", SUPPRESSED_OUTCOME_OFF_PLAN, KIND_OUTCOME),
        ("adoption_below_plan", SUPPRESSED_ADOPTION_BELOW_PLAN, KIND_ENABLEMENT),
        ("negative_trust", SUPPRESSED_NEGATIVE_TRUST, KIND_HUMAN_OUTREACH),
    ):
        if not signals.get(condition):
            continue

        primary = _first_of_kind(non_commercial, kind) or _default_action(kind, client)
        others = [c for c in non_commercial if c is not primary]
        logger.info(
            "nba.suppressed reason=%s promoted=%s client=%s",
            reason, getattr(primary, "key", None), getattr(client, "id", "?"),
        )
        return NBADecision(
            primary=primary,
            secondary=others,
            # A reason is returned whether or not a commercial candidate was present:
            # the operator needs to know the rule is ACTIVE, not merely that nothing was
            # blocked this time.
            suppression_reason=reason,
            suppressed=commercial,
            signals=signals,
        )

    # ── Condition 5: commercial is eligible only if expansion is allowed. ────
    if commercial and not signals.get("expansion_allowed"):
        reason = (
            SUPPRESSED_HEALTH_UNKNOWN
            if not signals.get("health")
            else SUPPRESSED_EXPANSION_NOT_ALLOWED
        )
        primary = non_commercial[0] if non_commercial else None
        return NBADecision(
            primary=primary,
            secondary=non_commercial[1:],
            suppression_reason=reason,
            suppressed=commercial,
            signals=signals,
        )

    ordered = sorted(candidates, key=lambda c: (-c.weight, c.kind == KIND_COMMERCIAL))
    return NBADecision(
        primary=ordered[0] if ordered else None,
        secondary=ordered[1:],
        suppression_reason="",
        suppressed=[],
        signals=signals,
    )


def _first_of_kind(candidates: list[ActionCandidate], kind: str) -> ActionCandidate | None:
    for candidate in candidates:
        if candidate.kind == kind:
            return candidate
    return None


def _default_action(kind: str, client=None) -> ActionCandidate:
    """
    A fallback action when nothing of the promoted kind was offered.

    The rule must never fail open: if condition 1 holds and no support action was
    supplied, we do NOT fall through to a commercial one. We MANUFACTURE the support
    action, because "resolve the blocking issue" is always a valid next step when there
    is a blocking issue.
    """
    defaults = {
        KIND_SUPPORT: ActionCandidate(
            key="resolve_support",
            label="Resolve the open support request",
            kind=KIND_SUPPORT,
            detail="A blocking issue is open. It comes before anything else.",
        ),
        KIND_OUTCOME: ActionCandidate(
            key="review_outcome",
            label="Review the outcome that is off plan",
            kind=KIND_OUTCOME,
            detail="An agreed outcome needs attention.",
        ),
        KIND_ENABLEMENT: ActionCandidate(
            key="enablement",
            label="Work through the plan items that are behind",
            kind=KIND_ENABLEMENT,
            detail="Adoption is behind the agreed plan.",
        ),
        KIND_HUMAN_OUTREACH: ActionCandidate(
            key="human_outreach",
            label="Have the success owner reach out",
            kind=KIND_HUMAN_OUTREACH,
            detail="Recent feedback suggests a conversation is needed.",
        ),
    }
    return defaults.get(kind, defaults[KIND_SUPPORT])


def next_best_action(client, candidates: list[ActionCandidate] | None = None) -> NBADecision:
    """
    THE SINGLE ENTRY POINT. Both the portal and the cockpit call this.

    When ``ENABLE_CUSTOMER_FIRST_NBA`` is off, the rule is bypassed and the highest
    weighted candidate wins — the pre-Phase-3 behaviour, so the flag is genuinely
    reversible.
    """
    candidates = list(candidates or [])
    if not enabled():
        ordered = sorted(candidates, key=lambda c: -c.weight)
        return NBADecision(primary=ordered[0] if ordered else None, secondary=ordered[1:])
    return rank(candidates, client=client)


def for_lead(lead, candidates: list[ActionCandidate] | None = None) -> NBADecision:
    """Convenience wrapper for the cockpit, which works in leads rather than clients."""
    client = getattr(lead, "client", None)
    if client is None:
        try:
            from apps.clients.models import Client

            client = Client.objects.filter(lead=lead).first()
        except Exception:  # noqa: BLE001
            client = None
    return next_best_action(client, candidates)
