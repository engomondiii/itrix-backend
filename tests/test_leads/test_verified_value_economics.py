"""Focused ASTOP verified-value economic translation regressions."""
from __future__ import annotations

import pytest

from apps.analytics.services import management_reporting
from apps.clients.serializers import PortalEvaluationSerializer
from apps.leads.models import ASTOPEngagement, ASTOPStage
from apps.leads.services.verified_value_economics import (
    SOURCE_ESTIMATED,
    SOURCE_MEASURED,
    customer_safe_verified_value,
    evaluate_economic_translation,
)
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def _translation(*, source=SOURCE_MEASURED, value=1200, with_basis=True):
    return {
        "value": value,
        "currency": "USD",
        "source_measurement": source,
        "cost_basis": (
            {"type": "cost", "reference": "customer-approved workload cost basis"}
            if with_basis
            else {}
        ),
        "assumptions": ["bounded to the evaluated workload and stated cost basis"],
        "provenance": {"source": "controlled evaluation economics worksheet"},
        "causal_scope": "bounded evaluated workload only",
    }


def _record(
    *,
    measured=20,
    estimated=25,
    fidelity="passed",
    translation=None,
    complete_proof=True,
):
    scope = {
        "workload": "bounded-workload",
        "observation_behavior": "controlled-observation",
        "model_or_controller": "controller-v1",
        "workflow": "reproducible-workflow",
    }
    if not complete_proof:
        scope.pop("workflow")
    return ASTOPEngagement.objects.create(
        lead=LeadFactory(),
        stage=ASTOPStage.VERIFY_EXPAND,
        evaluation_scope=scope,
        baseline={"measurement_window": "60m"},
        decision_fidelity={"status": fidelity},
        measured_savings={"value": measured, "provenance": "metered-run"},
        estimated_savings={"value": estimated, "provenance": "modelled-estimate"},
        security_result={"status": "passed"},
        integration_feasibility={"status": "passed"},
        evaluation_result={"status": "passed", "reproducible": True},
        verified_value={
            "status": "verified",
            "basis": "controlled proof",
            **({"economic_translation": translation} if translation is not None else {}),
        },
    )


def test_measured_technical_result_with_valid_cost_basis_allows_bounded_economics():
    record = _record(translation=_translation(source=SOURCE_MEASURED, value=1200))

    result = evaluate_economic_translation(record)

    assert result.available is True
    assert result.verified is True
    assert result.status == SOURCE_MEASURED
    assert result.value == 1200
    assert result.cost_basis["reference"] == "customer-approved workload cost basis"
    assert result.assumptions == ["bounded to the evaluated workload and stated cost basis"]
    assert result.provenance == {"source": "controlled evaluation economics worksheet"}


def test_estimated_source_remains_explicitly_estimated():
    record = _record(translation=_translation(source=SOURCE_ESTIMATED, value=1500))

    result = evaluate_economic_translation(record)
    safe = customer_safe_verified_value(record)

    assert result.available is True
    assert result.verified is False
    assert result.status == SOURCE_ESTIMATED
    assert safe["economic"]["status"] == SOURCE_ESTIMATED
    assert safe["economic"]["sourceMeasurement"] == SOURCE_ESTIMATED
    assert safe["economic"]["verified"] is False


def test_no_cost_or_capacity_basis_means_no_economic_translation():
    record = _record(translation=_translation(with_basis=False))

    result = evaluate_economic_translation(record)

    assert result.available is False
    assert result.value is None
    assert "cost_or_capacity_basis_required" in result.reasons


def test_fidelity_failure_blocks_verified_economic_value():
    record = _record(fidelity="failed", translation=_translation())

    result = evaluate_economic_translation(record)

    assert result.available is False
    assert result.verified is False
    assert "proof_contract_not_verified" in result.reasons


def test_incomplete_proof_blocks_verified_economic_value():
    record = _record(complete_proof=False, translation=_translation())

    result = evaluate_economic_translation(record)

    assert result.available is False
    assert "proof_contract_not_verified" in result.reasons


def test_null_economic_value_remains_unavailable_not_zero():
    record = _record(translation=_translation(value=None))

    result = evaluate_economic_translation(record)

    assert result.available is False
    assert result.value is None
    assert "economic_value_unavailable" in result.reasons


def test_measured_zero_remains_legitimate_zero():
    record = _record(measured=0, translation=_translation(source=SOURCE_MEASURED, value=0))

    result = evaluate_economic_translation(record)
    safe = customer_safe_verified_value(record)

    assert result.available is True
    assert result.value == 0
    assert safe["technical"]["measured"]["available"] is True
    assert safe["technical"]["measured"]["value"] == 0
    assert safe["economic"]["value"] == 0


def test_bare_savings_percentage_does_not_create_economic_value():
    record = _record(measured=30, translation=None)

    result = evaluate_economic_translation(record)

    assert result.available is False
    assert result.value is None
    assert "economic_translation_unavailable" in result.reasons


def test_customer_safe_serialization_never_overstates_estimate_as_measured():
    record = _record(translation=_translation(source=SOURCE_ESTIMATED, value=1500))
    safe = customer_safe_verified_value(record)

    payload = PortalEvaluationSerializer(
        {
            "exists": True,
            "kind": "astop",
            "stage": record.stage,
            "astopStage": record.stage,
            "kpis": [],
            "reportHref": "",
            "verifiedValue": safe,
        }
    ).data

    assert payload["verifiedValue"]["economic"]["status"] == SOURCE_ESTIMATED
    assert payload["verifiedValue"]["economic"]["verified"] is False
    assert payload["verifiedValue"]["technical"]["estimated"]["sourceMeasurement"] == SOURCE_ESTIMATED
    assert "provenance" not in str(payload).lower()
    assert "cost_basis" not in str(payload).lower()


def test_legacy_raw_verified_value_does_not_leak_internal_economic_translation():
    record = _record(translation=_translation(source=SOURCE_MEASURED, value=1200))

    payload = PortalEvaluationSerializer(
        {
            "exists": True,
            "kind": "astop",
            "stage": record.stage,
            "astopStage": record.stage,
            "kpis": [],
            "reportHref": "",
            "verifiedValue": record.verified_value,
        }
    ).data

    assert payload["verifiedValue"] == {"status": "verified", "basis": "controlled proof"}


def test_management_reporting_counts_measured_estimated_and_unavailable_economics():
    _record(translation=_translation(source=SOURCE_MEASURED, value=1200))
    _record(translation=_translation(source=SOURCE_ESTIMATED, value=1500))
    _record(translation=None)

    counts = management_reporting.summary()["astop"]["economicTranslation"]

    assert counts == {"measured": 1, "estimated": 1, "unavailable": 1}
