"""Governed ASTOP License-Out entitlement lifecycle.

The ASTOP engagement remains the single entitlement record. This service does not create
another licensing database; it gives the existing execution/expiry/revocation fields one
writer for entitlement lifecycle changes while preserving commercial progression as the
authority for progression and production-entitlement prerequisites.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.leads.models import ASTOPEngagement, ASTOPStage, Lead, LeadActivity
from apps.leads.services.commercial_progression import (
    _production_entitlement_reasons,
    _stage_gate_reasons,
    _unique_reasons,
)
from apps.leads.services.lo_terms import governed_terms_gate
from apps.leads.services.readiness import readiness_gate


ACTIVE_STATUSES = {"active", "authorized", "enabled"}
BLOCKING_REVOCATION_STATUSES = {"revoked", "revoking", "suspended", "blocked"}
TERMINAL_STATES = {"expired", "revoked"}
ENTITLEMENT_STAGES = {ASTOPStage.LO_DEPLOYMENT, ASTOPStage.VERIFY_EXPAND}
_ENTITLEMENT_WRITES: ContextVar[frozenset[str]] = ContextVar(
    "itrix_governed_entitlement_writes", default=frozenset()
)


@dataclass(frozen=True)
class EntitlementLifecycleResult:
    record: ASTOPEngagement
    previous_state: str
    current_state: str
    changed: bool


def _normal(value) -> str:
    return str(value or "").strip().lower()


def is_governed_entitlement_write(record_id) -> bool:
    """True only while this service owns an ASTOP entitlement-state mutation."""
    return str(record_id) in _ENTITLEMENT_WRITES.get()


def entitlement_lifecycle_state(record: ASTOPEngagement, *, now=None) -> str:
    """Derive the truthful entitlement state without turning missing data into active."""
    now = now or timezone.now()
    status = _normal(record.entitlement_status)
    revocation = _normal(record.revocation_status)

    if status == "revoked" or revocation == "revoked":
        return "revoked"
    if revocation in {"revoking", "suspended", "blocked"}:
        return revocation
    if status in {"revoking", "suspended", "blocked"}:
        return status
    if revocation not in {"", "none", "cleared"}:
        return "blocked"
    if status == "expired":
        return "expired"
    if record.entitlement_expires_at is not None and record.entitlement_expires_at <= now:
        return "expired"
    if status in ACTIVE_STATUSES:
        return "active"
    if status in {"", "pending"}:
        return "pending"
    return "unknown"


def _actor_name(by) -> str:
    return getattr(by, "display_name", "") or getattr(by, "email", "") or "system"


def _audit(
    lead: Lead,
    *,
    action: str,
    previous_state: str,
    current_state: str,
    reason: str,
    by=None,
) -> None:
    LeadActivity.objects.create(
        lead=lead,
        type=LeadActivity.ActivityType.STATUS_CHANGE,
        label=f"ASTOP entitlement {action}: {previous_state} → {current_state}.",
        by=by,
        by_name=_actor_name(by),
        meta={
            "domain": "astop_entitlement",
            "action": action,
            "from": previous_state,
            "to": current_state,
            "reason": str(reason or "").strip(),
        },
    )


@transaction.atomic
def update_astop_entitlement(
    lead: Lead,
    *,
    action: str,
    expires_at=None,
    reason: str = "",
    by=None,
) -> EntitlementLifecycleResult:
    """Activate, expire or revoke the existing ASTOP License-Out entitlement."""
    record = ASTOPEngagement.objects.select_for_update().filter(lead=lead).first()
    if record is None:
        raise ValueError("astop_entitlement_gate:astop_engagement_required")
    if record.stage not in ENTITLEMENT_STAGES:
        raise ValueError("astop_entitlement_gate:license_out_stage_required")

    action = _normal(action)
    if action not in {"activate", "expire", "revoke"}:
        raise ValueError("astop_entitlement_gate:invalid_entitlement_action")

    now = timezone.now()
    before = entitlement_lifecycle_state(record, now=now)
    previous_expiry = record.entitlement_expires_at

    if action == "activate":
        if before in TERMINAL_STATES or before in {"revoking", "suspended", "blocked", "unknown"}:
            raise ValueError(f"astop_entitlement_gate:{before}_entitlement_cannot_activate")
        if expires_at is not None and expires_at <= now:
            raise ValueError("astop_entitlement_gate:future_entitlement_expiry_required")
        if before == "active" and (expires_at is None or expires_at == previous_expiry):
            return EntitlementLifecycleResult(record, before, before, False)

        record.entitlement_status = "active"
        if expires_at is not None:
            record.entitlement_expires_at = expires_at

        reasons = list(_stage_gate_reasons(lead, record, record.stage))
        reasons.extend(_production_entitlement_reasons(record))
        reasons.extend(governed_terms_gate(record))
        reasons.extend(readiness_gate(record))
        reasons = list(_unique_reasons(reasons))
        if reasons:
            raise ValueError("astop_entitlement_gate:" + ",".join(reasons))

    elif action == "expire":
        if before == "expired":
            return EntitlementLifecycleResult(record, before, before, False)
        if before != "active":
            raise ValueError("astop_entitlement_gate:active_entitlement_required_for_expiry")
        record.entitlement_status = "expired"
        if record.entitlement_expires_at is None or record.entitlement_expires_at > now:
            record.entitlement_expires_at = now

    else:
        if before == "revoked":
            return EntitlementLifecycleResult(record, before, before, False)
        if before == "expired":
            raise ValueError("astop_entitlement_gate:expired_entitlement_cannot_revoke")
        record.entitlement_status = "revoked"
        record.revocation_status = "revoked"

    current = _ENTITLEMENT_WRITES.get()
    token = _ENTITLEMENT_WRITES.set(current | {str(record.pk)})
    try:
        record.save(
            update_fields=[
                "entitlement_status",
                "entitlement_expires_at",
                "revocation_status",
                "updated_at",
            ]
        )
    finally:
        _ENTITLEMENT_WRITES.reset(token)

    after = entitlement_lifecycle_state(record)
    changed = before != after or previous_expiry != record.entitlement_expires_at
    if changed:
        _audit(
            lead,
            action=action,
            previous_state=before,
            current_state=after,
            reason=reason,
            by=by,
        )
    return EntitlementLifecycleResult(record, before, after, changed)
