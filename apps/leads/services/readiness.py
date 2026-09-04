"""Truthful ASTOP production-readiness state inside the existing engagement record."""
from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.leads.models import ASTOPEngagement, ASTOPStage, Lead, LeadActivity

READINESS_KEYS = (
    "threat_model",
    "data_flow_disclosure",
    "retention_policy",
    "signed_build_availability",
    "build_integrity",
    "security_review",
    "reverse_engineering_protection_review",
    "entitlement_infrastructure",
    "update_revocation",
    "incident_response",
    "deployment_package",
)
READINESS_STATUSES = {
    "NOT_PROVIDED", "PENDING", "IN_REVIEW", "READY", "APPROVED", "BLOCKED", "FAILED"
}
PASSING_STATUSES = {"READY", "APPROVED"}
BLOCKING_STATUSES = {"BLOCKED", "FAILED"}


@dataclass(frozen=True)
class ReadinessResult:
    record: ASTOPEngagement
    readiness: dict
    changed: bool


def _scope(record: ASTOPEngagement) -> dict:
    return record.lo_scope if isinstance(record.lo_scope, dict) else {}


def current_readiness(record: ASTOPEngagement) -> dict:
    stored = _scope(record).get("release_readiness")
    stored = stored if isinstance(stored, dict) else {}
    result = {}
    for key in READINESS_KEYS:
        value = stored.get(key)
        if isinstance(value, dict):
            status = str(value.get("status") or "NOT_PROVIDED").upper()
            result[key] = {**value, "status": status if status in READINESS_STATUSES else "NOT_PROVIDED"}
        elif isinstance(value, str):
            status = value.upper()
            result[key] = {"status": status if status in READINESS_STATUSES else "NOT_PROVIDED"}
        else:
            result[key] = {"status": "NOT_PROVIDED"}
    return result


def overall_readiness_state(record: ASTOPEngagement) -> str:
    statuses = [row["status"] for row in current_readiness(record).values()]
    if any(status in BLOCKING_STATUSES for status in statuses):
        return "BLOCKED"
    if statuses and all(status in PASSING_STATUSES for status in statuses):
        return "READY"
    if any(status == "IN_REVIEW" for status in statuses):
        return "IN_REVIEW"
    if any(status == "PENDING" for status in statuses):
        return "PENDING"
    return "NOT_PROVIDED"


def readiness_gate(record: ASTOPEngagement) -> tuple[str, ...]:
    reasons = []
    for key, row in current_readiness(record).items():
        status = row["status"]
        if status not in PASSING_STATUSES:
            reasons.append(f"readiness_{key}_{status.lower()}")
    return tuple(reasons)


def _actor_name(by) -> str:
    return getattr(by, "display_name", "") or getattr(by, "email", "") or "system"


@transaction.atomic
def set_astop_readiness(lead: Lead, *, updates: dict, by) -> ReadinessResult:
    if not getattr(by, "is_authenticated", False) or getattr(by, "role", "") != "ADMIN":
        raise PermissionError("admin_required_for_astop_readiness")
    record = ASTOPEngagement.objects.select_for_update().filter(lead=lead).first()
    if record is None:
        raise ValueError("astop_readiness:astop_engagement_required")
    if record.stage == ASTOPStage.CLOSED:
        raise ValueError("astop_readiness:closed_engagement_cannot_change_readiness")
    if not isinstance(updates, dict) or not updates:
        raise ValueError("astop_readiness:readiness_updates_required")

    invalid_keys = sorted(set(updates) - set(READINESS_KEYS))
    if invalid_keys:
        raise ValueError("astop_readiness:invalid_readiness_key:" + ",".join(invalid_keys))

    existing = current_readiness(record)
    merged = {key: dict(value) for key, value in existing.items()}
    now = timezone.now().isoformat()
    changed = False
    for key, raw in updates.items():
        row = raw if isinstance(raw, dict) else {"status": raw}
        status = str(row.get("status") or "").upper()
        if status not in READINESS_STATUSES:
            raise ValueError(f"astop_readiness:invalid_readiness_status:{key}")
        reference = str(row.get("reference") or "").strip()
        old = merged[key]
        if old.get("status") == status and str(old.get("reference") or "") == reference:
            continue
        merged[key] = {
            "status": status,
            "reference": reference,
            "updated_at": now,
            "updated_by": str(getattr(by, "id", "") or ""),
        }
        changed = True

    if not changed:
        return ReadinessResult(record, existing, False)

    scope = dict(_scope(record))
    scope["release_readiness"] = merged
    record.lo_scope = scope
    record.save(update_fields=["lo_scope", "updated_at"])
    LeadActivity.objects.create(
        lead=lead,
        type=LeadActivity.ActivityType.STATUS_CHANGE,
        label=f"ASTOP production readiness updated ({overall_readiness_state(record)}).",
        by=by,
        by_name=_actor_name(by),
        meta={"domain": "astop_readiness", "overall": overall_readiness_state(record)},
    )
    return ReadinessResult(record, merged, True)
