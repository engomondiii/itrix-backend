"""Governed human review over existing trust/readiness/LO/entitlement records.

No new review database is introduced. Trust screening stays on ``Lead.trust_screening``;
``LeadActivity`` remains the durable audit history. Existing readiness, governed
License-Out and entitlement services remain their authoritative writers.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.leads.models import ASTOPEngagement, Lead, LeadActivity, TrustStatus

_ALLOWED_REVIEWER_ROLES = {"ADMIN", "ASSESSMENT", "SPECIALIST"}
_TRUST_REVIEW_WRITES: ContextVar[frozenset[str]] = ContextVar(
    "itrix_governed_trust_review_writes", default=frozenset()
)


@dataclass(frozen=True)
class TrustReviewResult:
    lead: Lead
    previous_status: str
    current_status: str
    reviewed_at: object


def _actor_name(by) -> str:
    return getattr(by, "display_name", "") or getattr(by, "email", "") or "system"


def _authorized_reviewer(by) -> bool:
    return bool(
        getattr(by, "is_authenticated", False)
        and getattr(by, "is_active", False)
        and getattr(by, "role", "") in _ALLOWED_REVIEWER_ROLES
    )


def is_governed_trust_review_write(lead_id) -> bool:
    """True only while ``resolve_trust_review`` owns the Lead trust-state write."""
    return str(lead_id) in _TRUST_REVIEW_WRITES.get()


def human_review_snapshot(lead: Lead) -> dict:
    """Safe internal review projection; never returns anti-abuse signal flags/thresholds."""
    screening = lead.trust_screening if isinstance(lead.trust_screening, dict) else {}
    human = screening.get("human_review") if isinstance(screening.get("human_review"), dict) else {}
    record = ASTOPEngagement.objects.filter(lead=lead).first()

    readiness_overall = "NOT_PROVIDED"
    readiness_blocker_count = 0
    lo_terms_status = "missing"
    entitlement_state = "inactive"
    if record is not None:
        from apps.leads.services.entitlement_lifecycle import entitlement_lifecycle_state
        from apps.leads.services.readiness import overall_readiness_state, readiness_gate

        readiness_overall = overall_readiness_state(record)
        readiness_blocker_count = len(readiness_gate(record))
        scope = record.lo_scope if isinstance(record.lo_scope, dict) else {}
        terms = scope.get("governed_terms") if isinstance(scope.get("governed_terms"), dict) else {}
        lo_terms_status = str(terms.get("status") or "missing").strip().lower() or "missing"
        entitlement_state = entitlement_lifecycle_state(record)

    trust_blocked = lead.trust_status in {TrustStatus.REVIEW, TrustStatus.REJECT}
    return {
        "leadId": str(lead.id),
        "trust": {
            "status": lead.trust_status,
            "pendingReview": lead.trust_status == TrustStatus.REVIEW,
            "blocked": trust_blocked,
            "escalated": bool(lead.escalated),
            # Safe internal narrative only. Raw copying/extraction/redistribution flags
            # and protected detection criteria deliberately do not cross this projection.
            "screeningRationale": str(screening.get("rationale") or "").strip(),
            "lastDecision": human.get("decision"),
            "reviewRationale": human.get("rationale"),
            "reviewerId": human.get("reviewer_id"),
            "reviewerName": human.get("reviewer_name"),
            "reviewedAt": human.get("reviewed_at"),
        },
        "astop": {
            "exists": record is not None,
            "stage": record.stage if record is not None else "",
            "readinessOverall": readiness_overall,
            "readinessBlockerCount": readiness_blocker_count,
            "governedLoTermsStatus": lo_terms_status,
            "entitlementState": entitlement_state,
        },
        "blocking": {
            "trust": trust_blocked,
            "productionReadiness": record is not None and readiness_overall != "READY",
            "licenseOutTerms": record is not None and lo_terms_status != "final",
            "entitlement": record is not None and entitlement_state != "active",
        },
    }


@transaction.atomic
def resolve_trust_review(
    lead: Lead,
    *,
    decision: str,
    rationale: str,
    by,
) -> TrustReviewResult:
    """Resolve/continue a trust REVIEW with reviewer/time and durable audit history."""
    if not _authorized_reviewer(by):
        raise PermissionError("authorized_internal_reviewer_required")

    locked = Lead.objects.select_for_update().get(pk=lead.pk)
    decision = str(decision or "").strip().lower()
    rationale = str(rationale or "").strip()
    if decision not in {TrustStatus.PASS, TrustStatus.REVIEW, TrustStatus.REJECT}:
        raise ValueError("trust_review:invalid_decision")
    if not rationale:
        raise ValueError("trust_review:rationale_required")

    previous = locked.trust_status
    if previous == TrustStatus.UNREVIEWED:
        raise ValueError("trust_review:screening_required_before_human_review")
    # There is no existing governed reconsideration flow in this repository. Therefore a
    # rejected prospect stays fail-closed; do not invent REJECT -> REVIEW/PASS semantics.
    if previous == TrustStatus.REJECT and decision != TrustStatus.REJECT:
        raise ValueError("trust_review:rejected_prospect_requires_governed_reconsideration")
    if previous == TrustStatus.PASS and not locked.escalated and decision != TrustStatus.PASS:
        raise ValueError("trust_review:non_escalated_pass_requires_new_screening")

    reviewed_at = timezone.now()
    screening = dict(locked.trust_screening or {})
    screening["status"] = decision
    screening["human_review"] = {
        "decision": decision,
        "rationale": rationale,
        "reviewer_id": str(getattr(by, "id", "") or ""),
        "reviewer_name": _actor_name(by),
        "reviewed_at": reviewed_at.isoformat(),
    }
    locked.trust_screening = screening
    locked.trust_status = decision
    if decision in {TrustStatus.REVIEW, TrustStatus.REJECT}:
        locked.escalated = True
        locked.escalated_at = locked.escalated_at or reviewed_at

    current = _TRUST_REVIEW_WRITES.get()
    token = _TRUST_REVIEW_WRITES.set(current | {str(locked.pk)})
    try:
        locked.save(
            update_fields=[
                "trust_screening",
                "trust_status",
                "escalated",
                "escalated_at",
                "updated_at",
            ]
        )
    finally:
        _TRUST_REVIEW_WRITES.reset(token)

    LeadActivity.objects.create(
        lead=locked,
        type=LeadActivity.ActivityType.STATUS_CHANGE,
        label=f"Trust review: {previous} → {decision}.",
        by=by,
        by_name=_actor_name(by),
        meta={
            "domain": "trust_review",
            "from": previous,
            "to": decision,
            "reviewer_id": str(getattr(by, "id", "") or ""),
            "reviewed_at": reviewed_at.isoformat(),
        },
    )

    # Trust is a substantive gate input. A review outcome and the denormalized product
    # gates must commit atomically so stale allow-state cannot survive a REJECT/REVIEW.
    from apps.leads.services.progression_state import sync_progression_state

    sync_progression_state(locked, by=by, audit=True)
    return TrustReviewResult(locked, previous, decision, reviewed_at)
