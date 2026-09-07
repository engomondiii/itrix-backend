"""Governed ASTOP License-Out terms inside the existing ASTOPEngagement record.

`ASTOPEngagement.lo_scope` remains the single LO-owned commercial/licensing record. This
module gives its `governed_terms` snapshot validation, provenance, immutability and
customer-safe projection without introducing another contract or licensing database.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.leads.models import ASTOPEngagement, ASTOPStage, Lead, LeadActivity, SpecialRights

TERM_STATUSES = {"draft", "negotiated", "final"}
EDITABLE_STAGES = {ASTOPStage.CONTROLLED_EVALUATION, ASTOPStage.LO_DEPLOYMENT}
_SCOPE_KEYS = {
    "business_unit", "product_scope", "field_of_use", "workload", "environments",
    "territory", "term", "deployment_scale", "deployment_scope",
}
_ECONOMICS_KEYS = {
    "access_fee", "annual_minimum", "scale_component", "support_security_upgrades",
    "expansion_terms", "currency",
}


@dataclass(frozen=True)
class GovernedTermsResult:
    record: ASTOPEngagement
    terms: dict
    changed: bool


def _text(value) -> str:
    return str(value or "").strip()


def _meaningful(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (dict, list, tuple, set)):
        return bool(value)
    return True


def _normal(value) -> str:
    return _text(value).casefold()


def _string_set(value) -> set[str]:
    if value is None:
        return set()
    values = [value] if isinstance(value, str) else value if isinstance(value, (list, tuple, set)) else [value]
    return {_normal(item) for item in values if _text(item)}


def _existing_terms(record: ASTOPEngagement) -> dict:
    scope = record.lo_scope if isinstance(record.lo_scope, dict) else {}
    terms = scope.get("governed_terms")
    return terms if isinstance(terms, dict) else {}


def _substantive_snapshot(terms: dict) -> dict:
    provenance = terms.get("provenance") if isinstance(terms.get("provenance"), dict) else {}
    return {
        "rights": terms.get("rights") if isinstance(terms.get("rights"), dict) else {},
        "economics": terms.get("economics") if isinstance(terms.get("economics"), dict) else {},
        "status": _text(terms.get("status")).lower(),
        "source_reference": _text(provenance.get("source_reference")),
    }


def validate_governed_terms_payload(lead: Lead, terms: dict) -> tuple[str, ...]:
    reasons: list[str] = []
    if not isinstance(terms, dict) or not terms:
        return ("governed_terms_required",)

    rights = terms.get("rights") if isinstance(terms.get("rights"), dict) else {}
    economics = terms.get("economics") if isinstance(terms.get("economics"), dict) else {}
    status = _text(terms.get("status")).lower()

    if not rights:
        reasons.append("governed_rights_required")
    rights_type = _text(rights.get("rights_type"))
    if rights_type not in set(SpecialRights.values):
        reasons.append("valid_special_rights_reference_required")
    if not _text(rights.get("licensed_party")):
        reasons.append("licensed_party_required")
    if not any(_meaningful(rights.get(key)) for key in _SCOPE_KEYS):
        reasons.append("licensed_scope_required")
    if "redistribution" not in rights or not _meaningful(rights.get("redistribution")):
        reasons.append("redistribution_terms_required")
    if "audit_terms" not in rights or not _meaningful(rights.get("audit_terms")):
        reasons.append("audit_terms_required")

    if not economics:
        reasons.append("governed_economics_required")
    elif not any(key in economics and _meaningful(economics.get(key)) for key in _ECONOMICS_KEYS):
        reasons.append("governed_economics_terms_required")

    if status not in TERM_STATUSES:
        reasons.append("governed_terms_status_required")

    client = getattr(lead, "client_account", None)
    verified_org = ""
    if client is not None and getattr(client, "organization_verified_at", None) is not None:
        verified_org = _text(getattr(client, "organization", ""))
    if verified_org and _normal(rights.get("licensed_party")) != _normal(verified_org):
        reasons.append("licensed_party_mismatch")

    return tuple(dict.fromkeys(reasons))


def _requested_scope(record: ASTOPEngagement) -> dict:
    lo_scope = record.lo_scope if isinstance(record.lo_scope, dict) else {}
    evaluation_scope = record.evaluation_scope if isinstance(record.evaluation_scope, dict) else {}
    return {
        "business_unit": _text(record.lead.business_unit),
        "field_of_use": lo_scope.get("field_of_use"),
        "environments": (
            lo_scope.get("environments") or lo_scope.get("environment")
            or evaluation_scope.get("environments") or evaluation_scope.get("environment")
        ),
        "deployment_scope": lo_scope.get("deployment_scope"),
    }


def governed_scope_reasons(record: ASTOPEngagement, terms: dict | None = None) -> tuple[str, ...]:
    terms = terms or _existing_terms(record)
    rights = terms.get("rights") if isinstance(terms.get("rights"), dict) else {}
    requested = _requested_scope(record)
    reasons: list[str] = []

    governed_business_unit = _text(rights.get("business_unit"))
    if governed_business_unit and requested["business_unit"] and _normal(governed_business_unit) != _normal(requested["business_unit"]):
        reasons.append("business_unit_outside_governed_scope")

    governed_field = _text(rights.get("field_of_use"))
    requested_field = _text(requested["field_of_use"])
    if governed_field and requested_field and _normal(governed_field) != _normal(requested_field):
        reasons.append("field_of_use_outside_governed_scope")

    governed_envs = _string_set(rights.get("environments"))
    requested_envs = _string_set(requested["environments"])
    if governed_envs and requested_envs and not requested_envs.issubset(governed_envs):
        reasons.append("environment_outside_governed_scope")

    governed_deployment = _string_set(rights.get("deployment_scope"))
    requested_deployment = _string_set(requested["deployment_scope"])
    if governed_deployment and requested_deployment and not requested_deployment.issubset(governed_deployment):
        reasons.append("deployment_outside_governed_scope")

    return tuple(dict.fromkeys(reasons))


def governed_terms_gate(record: ASTOPEngagement) -> tuple[str, ...]:
    terms = _existing_terms(record)
    reasons = list(validate_governed_terms_payload(record.lead, terms))
    if terms and _text(terms.get("status")).lower() != "final":
        reasons.append("final_governed_terms_required")
    reasons.extend(governed_scope_reasons(record, terms))
    return tuple(dict.fromkeys(reasons))


def _actor_name(by) -> str:
    return getattr(by, "display_name", "") or getattr(by, "email", "") or "system"


def _audit(lead: Lead, *, status: str, source_reference: str, by) -> None:
    LeadActivity.objects.create(
        lead=lead,
        type=LeadActivity.ActivityType.STATUS_CHANGE,
        label=f"ASTOP License-Out governed terms updated ({status}).",
        by=by,
        by_name=_actor_name(by),
        meta={"domain": "astop_lo_terms", "status": status, "source_reference": source_reference},
    )


@transaction.atomic
def set_governed_lo_terms(
    lead: Lead,
    *,
    rights: dict,
    economics: dict,
    status: str,
    source_reference: str = "",
    by,
) -> GovernedTermsResult:
    """Create/update the governed LO snapshot before execution.

    Once an LO is executed, only an identical replay is accepted. Amendments fail closed
    because this repository has no authoritative LO-amendment workflow to delegate to.
    """
    if not getattr(by, "is_authenticated", False) or getattr(by, "role", "") != "ADMIN":
        raise PermissionError("admin_required_for_governed_lo_terms")

    record = ASTOPEngagement.objects.select_for_update().filter(lead=lead).first()
    if record is None:
        raise ValueError("governed_lo_terms:astop_engagement_required")
    if record.stage not in EDITABLE_STAGES and record.lo_executed_at is None:
        raise ValueError("governed_lo_terms:license_out_terms_stage_required")

    requested = {
        "rights": dict(rights or {}),
        "economics": dict(economics or {}),
        "status": _text(status).lower(),
        "provenance": {"source_reference": _text(source_reference)},
    }
    reasons = validate_governed_terms_payload(lead, requested)
    if reasons:
        raise ValueError("governed_lo_terms:" + ",".join(reasons))

    existing = _existing_terms(record)
    if existing and _substantive_snapshot(existing) == _substantive_snapshot(requested):
        return GovernedTermsResult(record, existing, False)

    if record.lo_executed_at is not None:
        if existing:
            raise ValueError("governed_lo_terms:executed_lo_governed_terms_immutable")
        raise ValueError("governed_lo_terms:executed_lo_snapshot_missing_manual_reconciliation_required")

    now = timezone.now()
    requested["provenance"] = {
        "setter_type": "team_user",
        "setter_id": str(getattr(by, "id", "") or ""),
        "setter_name": _actor_name(by),
        "recorded_at": now.isoformat(),
        "source_reference": _text(source_reference),
    }
    lo_scope = dict(record.lo_scope or {})
    lo_scope["governed_terms"] = requested
    record.lo_scope = lo_scope
    record.save(update_fields=["lo_scope", "updated_at"])

    rights_type = requested["rights"].get("rights_type")
    if rights_type and lead.special_rights != rights_type:
        lead.special_rights = rights_type
        lead.save(update_fields=["special_rights", "updated_at"])

    _audit(lead, status=requested["status"], source_reference=requested["provenance"]["source_reference"], by=by)
    return GovernedTermsResult(record, requested, True)


def customer_safe_lo_summary(record: ASTOPEngagement | None) -> dict:
    """High-level client projection. Economics, provenance and audit terms never cross."""
    if record is None:
        return {
            "loStatus": "not_started",
            "licensedScopeSummary": None,
            "entitlementState": "inactive",
            "entitlementExpiresAt": None,
            "nextRequiredAction": "continue_evaluation",
        }

    terms = _existing_terms(record)
    status = _text(terms.get("status")).lower()
    rights = terms.get("rights") if isinstance(terms.get("rights"), dict) else {}
    scope_summary = None
    if status == "final" and rights:
        scope_summary = {
            key: rights.get(key)
            for key in (
                "rights_type", "licensed_party", "business_unit", "product_scope",
                "field_of_use", "workload", "environments", "territory", "term",
                "deployment_scale", "deployment_scope", "redistribution",
            )
            if _meaningful(rights.get(key))
        }

    from apps.leads.services.entitlement_lifecycle import entitlement_lifecycle_state

    entitlement_state = entitlement_lifecycle_state(record)
    lo_status = "executed" if record.lo_executed_at is not None else "negotiating" if terms else "not_started"
    if not terms or status != "final":
        next_action = "finalize_license_out_terms"
    elif record.lo_executed_at is None:
        next_action = "execute_license_out"
    elif entitlement_state != "active":
        next_action = "activate_entitlement"
    else:
        next_action = "none"

    return {
        "loStatus": lo_status,
        "licensedScopeSummary": scope_summary,
        "entitlementState": entitlement_state,
        "entitlementExpiresAt": record.entitlement_expires_at,
        "nextRequiredAction": next_action,
    }
