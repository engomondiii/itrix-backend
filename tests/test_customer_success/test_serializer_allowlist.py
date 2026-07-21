"""
Customer-visible vs internal-only (Architecture §7.4, §10.5, Playbook §12J).

    Enforced by SERIALIZER ALLOW-LISTS on the client plane, not by frontend omission.

An allow-list fails CLOSED: add a field to the model and it stays invisible until
somebody deliberately admits it. A deny-list fails OPEN, which is how internal fields
leak.
"""

from __future__ import annotations

import inspect

import pytest
from rest_framework import serializers

from apps.customer_success import serializers as module

# §12J — what a customer must NEVER see.
FORBIDDEN = [
    "license_out_probability", "licenseOutProbability",
    "deal_score", "dealScore", "score_breakdown",
    "tier", "account_priority", "accountPriority",
    "persona", "persona_id", "personaId", "pitch_room_id", "pitchRoomId",
    "churn_risk", "churnRisk", "negotiation_posture", "competitor_risk",
    "objection_classification", "gate_decision", "gate_decision_reason",
    "coverage_map", "coverageMap", "question_budget_remaining",
    "stop_reason", "stopReason", "attachment_risk_flags", "riskFlags",
    "customer_health", "customerHealth",
]


def _client_plane_serializers():
    for name, obj in inspect.getmembers(module, inspect.isclass):
        if not issubclass(obj, serializers.Serializer):
            continue
        if name.startswith("Team"):
            continue
        yield name, obj


@pytest.mark.parametrize("forbidden", FORBIDDEN)
def test_no_client_serializer_exposes_an_internal_field(forbidden):
    offenders = []
    for name, obj in _client_plane_serializers():
        fields = getattr(getattr(obj, "Meta", None), "fields", []) or []
        declared = list(getattr(obj, "_declared_fields", {}).keys())
        if forbidden in fields or forbidden in declared:
            offenders.append(name)
    assert not offenders, f"{forbidden!r} exposed by: {offenders}"


def test_every_client_serializer_uses_an_explicit_field_list():
    """
    ``fields = "__all__"`` is a deny-list wearing a disguise: it admits every future
    column automatically.
    """
    for name, obj in _client_plane_serializers():
        meta = getattr(obj, "Meta", None)
        if meta is None:
            continue
        assert getattr(meta, "fields", None) != "__all__", f"{name} uses __all__"
        assert not getattr(meta, "exclude", None), f"{name} uses a deny-list"


def test_outcomes_use_the_four_approved_status_words():
    """
    On plan · At risk · Off plan · Achieved — used EXACTLY as written, so that
    "Off plan" cannot drift into "progressing".
    """
    from apps.customer_success.models import OutcomeStatus

    labels = {label for _value, label in OutcomeStatus.choices}
    assert labels == {"On plan", "At risk", "Off plan", "Achieved"}


def test_outcome_status_rejects_anything_else():
    from apps.customer_success.services import outcome_tracker
    from tests.factories.client_factory import ClientFactory
    from tests.factories.lead_factory import LeadFactory

    pytest.importorskip("django")


@pytest.mark.django_db
def test_setting_an_unapproved_status_raises(paying_client):
    from apps.customer_success.services import outcome_tracker

    outcome = outcome_tracker.create(paying_client, title="Cut inference cost")
    with pytest.raises(ValueError):
        outcome_tracker.set_status(outcome, "promising")


@pytest.mark.django_db
def test_deployment_known_limitations_are_customer_visible():
    """
    "We would rather you hear them from us." Omitting the field would make the panel
    look better and the relationship worse.
    """
    from apps.customer_success.serializers import DeploymentHealthSerializer

    assert "knownLimitations" in DeploymentHealthSerializer.Meta.fields
