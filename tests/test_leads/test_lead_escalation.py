"""Lead escalation tests."""

from __future__ import annotations

import pytest

from apps.leads.models import LeadActivity
from apps.leads.services.lead_escalator import escalate_lead
from apps.leads.services.exclusive_flag_handler import (
    approval_checklist,
    evaluate_exclusive_flag,
)
from tests.factories.lead_factory import LeadFactory
from tests.factories.user_factory import AdminUserFactory

pytestmark = pytest.mark.django_db


def test_escalate_sets_flags_and_logs():
    lead = LeadFactory(escalated=False, human_handoff_trigger=False)
    user = AdminUserFactory()
    escalate_lead(lead, reason="Strategic opportunity", by=user)
    lead.refresh_from_db()
    assert lead.escalated is True
    assert lead.human_handoff_trigger is True
    assert lead.escalated_at is not None
    assert LeadActivity.objects.filter(lead=lead, type=LeadActivity.ActivityType.ESCALATED).exists()


def test_escalate_is_idempotent():
    lead = LeadFactory()
    escalate_lead(lead, reason="first")
    first_time = lead.escalated_at
    escalate_lead(lead, reason="second")
    lead.refresh_from_db()
    # escalated_at is preserved on the second call.
    assert lead.escalated_at == first_time


def test_exclusive_flag_for_strategic():
    result = evaluate_exclusive_flag(commercial_path="strategic", answers={}, tier=1)
    assert result.is_exclusive is True
    assert result.requires_human_review is True
    assert result.special_rights == "Exclusive-Global"


def test_exclusive_flag_for_non_exclusive():
    result = evaluate_exclusive_flag(commercial_path="non_exclusive", answers={}, tier=3)
    assert result.is_exclusive is False
    assert result.requires_human_review is False


def test_tier1_requires_human_review_even_without_exclusivity():
    result = evaluate_exclusive_flag(commercial_path=None, answers={}, tier=1)
    assert result.requires_human_review is True


def test_approval_checklist_has_seven_items():
    items = approval_checklist()
    assert len(items) == 7
    assert all("label" in i and "id" in i for i in items)


# ── API ──────────────────────────────────────────────────────────────────────
def _auth(api_client):
    from tests.factories.user_factory import AdminUserFactory as AUF, DEFAULT_PASSWORD

    AUF(email="esc@itrix.example", name="Esc User")
    resp = api_client.post(
        "/api/v1/auth/login/",
        {"email": "esc@itrix.example", "password": DEFAULT_PASSWORD},
        format="json",
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.json()['access']}")


def test_escalate_action(api_client):
    lead = LeadFactory()
    _auth(api_client)
    resp = api_client.post(f"/api/v1/leads/{lead.id}/escalate/", {"reason": "x"}, format="json")
    assert resp.status_code == 200
    assert resp.json()["humanHandoffTrigger"] is True


def test_approval_checklist_endpoint(api_client):
    _auth(api_client)
    resp = api_client.get("/api/v1/leads/approval-checklist/")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 7


def test_handoff_memo_endpoint(api_client):
    lead = LeadFactory()
    _auth(api_client)
    resp = api_client.get(f"/api/v1/leads/{lead.id}/handoff/")
    assert resp.status_code == 200
    assert "Lead Handoff Memo" in resp.json()["memo"]
