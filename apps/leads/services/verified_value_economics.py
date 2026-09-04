"""Governed translation from ASTOP proof evidence to bounded economic value.

Technical savings and economic value are deliberately separate. This module never
multiplies percentages, invents rates, or infers customer economics. It only validates an
explicit economic translation recorded inside the existing ``verified_value`` JSON and
projects it with its measured/estimated status preserved.
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.leads.models import ASTOPEngagement

SOURCE_MEASURED = "MEASURED"
SOURCE_ESTIMATED = "ESTIMATED"
SOURCE_KINDS = {SOURCE_MEASURED, SOURCE_ESTIMATED}
COST_BASIS_TYPES = {"cost", "capacity", "cost_and_capacity"}


@dataclass(frozen=True)
class EconomicTranslation:
    available: bool
    verified: bool
    status: str
    source_measurement: str | None
    value: object | None
    currency: str | None
    unit: str | None
    cost_basis: dict
    assumptions: object
    provenance: object
    reasons: tuple[str, ...]


def _text(value) -> str:
    return str(value or "").strip()


def _metric(payload) -> tuple[bool, object | None, bool]:
    if not isinstance(payload, dict) or "value" not in payload:
        return False, None, False
    value = payload.get("value")
    available = value is not None
    provenance = any(
        _text(payload.get(key))
        for key in ("provenance", "source", "basis", "measurement_source")
    )
    return available, value, provenance


def _economic_payload(record: ASTOPEngagement) -> dict:
    verified = record.verified_value if isinstance(record.verified_value, dict) else {}
    payload = verified.get("economic_translation")
    return payload if isinstance(payload, dict) else {}


def evaluate_economic_translation(record: ASTOPEngagement) -> EconomicTranslation:
    """Validate a recorded translation without creating economics from technical data."""
    # Lazy import avoids a module cycle: commercial_progression owns the proof gate and
    # imports the ASTOP model; this service is a consumer of that gate, not another gate.
    from apps.leads.services.commercial_progression import controlled_evaluation_proof_gate

    reasons: list[str] = []
    proof = controlled_evaluation_proof_gate(record)
    if not proof.allowed:
        reasons.append("proof_contract_not_verified")
    if not record.has_verified_value:
        reasons.append("verified_value_state_required")

    payload = _economic_payload(record)
    if not payload:
        reasons.append("economic_translation_unavailable")

    source = _text(payload.get("source_measurement")).upper()
    if source not in SOURCE_KINDS:
        reasons.append("explicit_source_measurement_required")

    if source == SOURCE_MEASURED:
        metric_available, _technical_value, metric_provenance = _metric(record.measured_savings)
    elif source == SOURCE_ESTIMATED:
        metric_available, _technical_value, metric_provenance = _metric(record.estimated_savings)
    else:
        metric_available, metric_provenance = False, False
    if source in SOURCE_KINDS and not metric_available:
        reasons.append("source_measurement_value_unavailable")
    if source in SOURCE_KINDS and not metric_provenance:
        reasons.append("source_measurement_provenance_required")

    cost_basis = payload.get("cost_basis") if isinstance(payload.get("cost_basis"), dict) else {}
    basis_type = _text(cost_basis.get("type")).lower()
    basis_reference = _text(cost_basis.get("reference"))
    if basis_type not in COST_BASIS_TYPES or not basis_reference:
        reasons.append("cost_or_capacity_basis_required")

    economic_value = payload.get("value") if "value" in payload else None
    if economic_value is None:
        reasons.append("economic_value_unavailable")

    currency = _text(payload.get("currency")) or None
    unit = _text(payload.get("unit")) or None
    if currency is None and unit is None:
        reasons.append("economic_value_unit_required")

    if "assumptions" not in payload:
        reasons.append("economic_assumptions_required")
    assumptions = payload.get("assumptions")
    provenance = payload.get("provenance")
    if not provenance:
        reasons.append("economic_provenance_required")
    if not _text(payload.get("causal_scope")):
        reasons.append("bounded_causal_scope_required")

    reasons = list(dict.fromkeys(reasons))
    available = not reasons
    return EconomicTranslation(
        available=available,
        verified=available and source == SOURCE_MEASURED,
        status=(source if available else "UNAVAILABLE"),
        source_measurement=(source if source in SOURCE_KINDS else None),
        value=(economic_value if available else None),
        currency=(currency if available else None),
        unit=(unit if available else None),
        cost_basis=(dict(cost_basis) if available else {}),
        assumptions=(assumptions if available else None),
        provenance=(provenance if available else None),
        reasons=tuple(reasons),
    )


def technical_value_summary(record: ASTOPEngagement) -> dict:
    """Keep measured and estimated technical evidence distinct; zero remains available."""
    measured_available, measured_value, _ = _metric(record.measured_savings)
    estimated_available, estimated_value, _ = _metric(record.estimated_savings)
    return {
        "measured": {
            "sourceMeasurement": SOURCE_MEASURED,
            "available": measured_available,
            "value": measured_value if measured_available else None,
        },
        "estimated": {
            "sourceMeasurement": SOURCE_ESTIMATED,
            "available": estimated_available,
            "value": estimated_value if estimated_available else None,
        },
    }


def customer_safe_verified_value(record: ASTOPEngagement | None) -> dict:
    """Customer-safe proof/economic projection with no internal basis or assumptions."""
    if record is None:
        return {
            "verified": False,
            "technical": {
                "measured": {"sourceMeasurement": SOURCE_MEASURED, "available": False, "value": None},
                "estimated": {"sourceMeasurement": SOURCE_ESTIMATED, "available": False, "value": None},
            },
            "economic": {
                "status": "UNAVAILABLE",
                "verified": False,
                "sourceMeasurement": None,
                "value": None,
                "currency": None,
                "unit": None,
            },
        }

    translation = evaluate_economic_translation(record)
    return {
        "verified": bool(record.has_verified_value),
        "technical": technical_value_summary(record),
        "economic": {
            "status": translation.status,
            "verified": translation.verified,
            "sourceMeasurement": translation.source_measurement,
            "value": translation.value,
            "currency": translation.currency,
            "unit": translation.unit,
            # This is a scope label, not a causal claim. It explicitly prevents a bounded
            # translation from being read as total-system cost reduction.
            "claimScope": "bounded_to_recorded_cost_or_capacity_basis" if translation.available else None,
        },
    }
