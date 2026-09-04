"""Focused governed human-review and operator-permission regressions."""
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.clients.tokens import build_tokens_for_client
from apps.evaluations.models import Evaluation, EvaluationPackage
from apps.leads.models import LeadActivity, TrustStatus
from apps.leads.services.commercial_progression import verified_counterparty_gate
from apps.leads.services.human_review import human_review_snapshot, resolve_trust_review
from tests.factories.client_factory import ClientFactory
from tests.factories.lead_factory import LeadFactory
from tests.factories.user_factory import AdminUserFactory, SpecialistUserFactory, ViewerUserFactory

pytestmark = pytest.mark.django_db


def _review_lead(*, verified=True):
    lead = LeadFactory(
        trust_status=TrustStatus.REVIEW,
        escalated=True,
        escalated_at=timezone.now(),
        trust_screening={
            "status": "review",
            "rationale": "Identity evidence requires human confirmation.",
            "copying_signal": True,
            "extraction_signal": True,
            "redistribution_signal": False,
        },
        commercial_progress={
            "astop_verified_value_gate": True,
            "alpha_compute_gate": True,
            "alpha_core_gate": True,
            "next_best_action": "stale_allow_state",
        },
    )
    now = timezone.now()
    ClientFactory(
        lead=lead,
        identity_verified_at=now if verified else None,
        organization_verified_at=now if verified else None,
    )
    return lead


def test_authorized_internal_reviewer_resolves_review_and_records_reviewer_timestamp_and_audit():
    lead = _review_lead()
    reviewer = SpecialistUserFactory()

    result = resolve_trust_review(
        lead,
        decision=TrustStatus.PASS,
        rationale="Verified against controlled identity evidence.",
        by=reviewer,
    )

    result.lead.refresh_from_db()
    human = result.lead.trust_screening["human_review"]
    assert result.lead.trust_status == TrustStatus.PASS
    assert human["decision"] == TrustStatus.PASS
    assert human["reviewer_id"] == str(reviewer.id)
    assert human["reviewer_name"] == reviewer.display_name
    assert human["reviewed_at"]
    assert result.reviewed_at is not None

    activity = LeadActivity.objects.get(lead=lead, meta__domain="trust_review")
    assert activity.by_id == reviewer.id
    assert activity.meta["from"] == TrustStatus.REVIEW
    assert activity.meta["to"] == TrustStatus.PASS
    assert activity.meta["reviewed_at"]


def test_review_and_reject_remain_fail_closed_for_sensitive_progression():
    review = _review_lead()
    assert verified_counterparty_gate(review).allowed is False
    assert "trust_review_required" in verified_counterparty_gate(review).reasons

    review.trust_status = TrustStatus.REJECT
    review.save(update_fields=["trust_status", "updated_at"])
    assert verified_counterparty_gate(review).allowed is False
    assert "trust_rejected" in verified_counterparty_gate(review).reasons


def test_pass_resolution_still_requires_unrelated_identity_and_entity_gates():
    lead = _review_lead(verified=False)
    resolve_trust_review(
        lead,
        decision=TrustStatus.PASS,
        rationale="Trust review cleared; identity verification remains pending.",
        by=AdminUserFactory(),
    )
    lead.refresh_from_db()

    decision = verified_counterparty_gate(lead)
    assert decision.allowed is False
    assert "verified_identity_required" in decision.reasons
    assert "verified_organization_required" in decision.reasons


def test_direct_reject_to_pass_or_review_is_blocked_without_reconsideration_flow():
    lead = _review_lead()
    lead.trust_status = TrustStatus.REJECT
    lead.trust_screening = {"status": "reject", "rationale": "Controlled rejection."}
    lead.save(update_fields=["trust_status", "trust_screening", "updated_at"])
    reviewer = AdminUserFactory()

    with pytest.raises(ValueError, match="governed_reconsideration"):
        resolve_trust_review(
            lead,
            decision=TrustStatus.PASS,
            rationale="Attempted direct reversal.",
            by=reviewer,
        )
    with pytest.raises(ValueError, match="governed_reconsideration"):
        resolve_trust_review(
            lead,
            decision=TrustStatus.REVIEW,
            rationale="Attempted ungoverned reopening.",
            by=reviewer,
        )


def test_review_snapshot_omits_raw_anti_abuse_signals_and_threshold_logic():
    lead = _review_lead()

    payload = human_review_snapshot(lead)
    serialized = str(payload).lower()

    assert payload["trust"]["pendingReview"] is True
    assert payload["trust"]["screeningRationale"]
    assert "copying_signal" not in serialized
    assert "extraction_signal" not in serialized
    assert "redistribution_signal" not in serialized
    assert "threshold" not in serialized


def test_trust_decision_resynchronizes_stale_substantive_product_gates():
    lead = _review_lead()

    resolve_trust_review(
        lead,
        decision=TrustStatus.REJECT,
        rationale="Sensitive progression rejected after human review.",
        by=AdminUserFactory(),
    )
    lead.refresh_from_db()

    assert lead.commercial_progress["astop_verified_value_gate"] is False
    assert lead.commercial_progress["alpha_compute_gate"] is False
    assert lead.commercial_progress["alpha_core_gate"] is False
    assert lead.commercial_progress["next_best_action"] == "continue_discovery"


def test_internal_review_endpoint_permissions_and_customer_separation(api_client):
    lead = _review_lead()
    url = f"/api/v1/leads/{lead.id}/trust-review/"

    reviewer = SpecialistUserFactory()
    api_client.force_authenticate(user=reviewer)
    response = api_client.post(
        url,
        {"decision": "pass", "rationale": "Controlled evidence verified."},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["trust"]["status"] == "pass"

    # A VIEWER can inspect team-safe state but cannot perform the protected mutation.
    other = _review_lead()
    other_url = f"/api/v1/leads/{other.id}/trust-review/"
    api_client.force_authenticate(user=ViewerUserFactory())
    assert api_client.get(other_url).status_code == 200
    assert api_client.post(
        other_url,
        {"decision": "pass", "rationale": "Not authorized."},
        format="json",
    ).status_code == 403

    # Client-plane credentials never authorize a team-plane trust-review operation.
    client_lead = _review_lead()
    client = client_lead.client_account
    token = build_tokens_for_client(client)["access"]
    customer_api = APIClient()
    customer_api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    customer_response = customer_api.post(
        f"/api/v1/leads/{client_lead.id}/trust-review/",
        {"decision": "pass", "rationale": "Customer cannot self-approve."},
        format="json",
    )
    assert customer_response.status_code in {401, 403}


def test_customer_identity_payload_has_no_trust_review_or_protected_rationale():
    lead = _review_lead()
    from apps.clients.serializers import ClientIdentitySerializer

    payload = ClientIdentitySerializer(lead.client_account).data
    serialized = str(payload).lower()
    assert "trust" not in serialized
    assert "rationale" not in serialized
    assert "copying" not in serialized
    assert "extraction" not in serialized


def test_iwl_override_remains_admin_only_and_records_bounded_audit(api_client):
    evaluation = Evaluation.objects.create(
        lead=LeadFactory(),
        pkg=EvaluationPackage.COMPUTE,
        standard_assessment_fee=Decimal("1000"),
    )
    url = f"/api/v1/evaluations/{evaluation.id}/iwl-override/"
    payload = {
        "waiver_type": "none",
        "reason": "Administrator confirms paid assessment treatment.",
        "final_fee": "1000.00",
    }

    api_client.force_authenticate(user=SpecialistUserFactory())
    assert api_client.post(url, payload, format="json").status_code == 403

    admin = AdminUserFactory()
    api_client.force_authenticate(user=admin)
    response = api_client.post(url, payload, format="json")
    assert response.status_code == 200

    evaluation.refresh_from_db()
    assert evaluation.iwl_override_applied is True
    assert evaluation.iwl_override_status == "none"
    assert evaluation.final_assessment_fee == Decimal("1000.00")
    activity = LeadActivity.objects.get(
        lead=evaluation.lead,
        meta__domain="iwl_fee_override",
        meta__evaluation_id=str(evaluation.id),
    )
    assert activity.by_id == admin.id
    assert activity.meta["waiver_type"] == "none"
    assert "reason" not in activity.meta
