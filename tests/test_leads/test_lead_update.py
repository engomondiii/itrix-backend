"""Lead update tests — status/owner/note via API, with activity logging."""

from __future__ import annotations

import pytest

from apps.leads.models import LeadActivity, LeadNote
from apps.leads.services.lead_updater import add_note, assign_owner, change_status
from tests.factories.lead_factory import LeadFactory
from tests.factories.user_factory import AdminUserFactory

pytestmark = pytest.mark.django_db


def test_change_status_logs_activity():
    lead = LeadFactory()
    user = AdminUserFactory()
    change_status(lead, status="Contacted", by=user)
    lead.refresh_from_db()
    assert lead.status == "Contacted"
    assert LeadActivity.objects.filter(lead=lead, type=LeadActivity.ActivityType.STATUS_CHANGE).exists()


def test_invalid_status_rejected():
    from apps.core.exceptions import ITrixError

    lead = LeadFactory()
    with pytest.raises(ITrixError):
        change_status(lead, status="Nonsense")


def test_assign_owner_logs_activity():
    lead = LeadFactory()
    owner = AdminUserFactory(name="Owner Person")
    assign_owner(lead, owner=owner)
    lead.refresh_from_db()
    assert lead.owner_id == owner.id
    assert LeadActivity.objects.filter(lead=lead, type=LeadActivity.ActivityType.OWNER_CHANGE).exists()


def test_add_note_creates_note_and_activity():
    lead = LeadFactory()
    user = AdminUserFactory()
    note = add_note(lead, body="Spoke with the customer.", by=user)
    assert isinstance(note, LeadNote)
    assert LeadNote.objects.filter(lead=lead).count() == 1
    assert LeadActivity.objects.filter(lead=lead, type=LeadActivity.ActivityType.NOTE).exists()


def test_first_response_stamped_on_leaving_new():
    lead = LeadFactory(status="New")
    assert lead.first_response_at is None
    change_status(lead, status="Contacted")
    lead.refresh_from_db()
    assert lead.first_response_at is not None


# ── API-level tests ──────────────────────────────────────────────────────────
def _auth(api_client):
    from tests.factories.user_factory import AdminUserFactory as AUF, DEFAULT_PASSWORD

    user = AUF(email="dash@itrix.example", name="Dash User")
    resp = api_client.post(
        "/api/v1/auth/login/",
        {"email": "dash@itrix.example", "password": DEFAULT_PASSWORD},
        format="json",
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.json()['access']}")
    return user


def test_lead_list_is_paginated_camelcase(api_client):
    LeadFactory.create_batch(3)
    _auth(api_client)
    resp = api_client.get("/api/v1/leads/")
    assert resp.status_code == 200
    body = resp.json()
    assert set(["results", "count", "page", "pageSize", "totalPages"]).issubset(body.keys())
    item = body["results"][0]
    assert "productRoute" in item and "commercialPath" in item and "specialRights" in item


def test_lead_detail_matches_web_shape(api_client):
    lead = LeadFactory()
    _auth(api_client)
    resp = api_client.get(f"/api/v1/leads/{lead.id}/")
    assert resp.status_code == 200
    keys = set(resp.json().keys())
    expected = {
        "id", "visitorName", "company", "email", "industry", "role", "productRoute",
        "commercialPath", "computeBottleneck", "primaryPain", "workloadType",
        "currentStack", "commercialIntent", "specialRights", "timeline", "score",
        "tier", "scoreBreakdown", "recommendedNextStep", "humanHandoffTrigger",
        "status", "owner", "ctaClicked", "documentsViewed", "submittedAt",
        "qualification", "notes", "activity",
    }
    assert expected.issubset(keys)


def test_status_action(api_client):
    lead = LeadFactory()
    _auth(api_client)
    resp = api_client.post(f"/api/v1/leads/{lead.id}/status/", {"status": "Contacted"}, format="json")
    assert resp.status_code == 200
    assert resp.json()["status"] == "Contacted"


def test_assign_by_email(api_client):
    lead = LeadFactory()
    user = _auth(api_client)
    resp = api_client.post(f"/api/v1/leads/{lead.id}/assign/", {"owner": user.email}, format="json")
    assert resp.status_code == 200
    assert resp.json()["owner"] == user.display_name


def test_note_action_then_detail_shows_note(api_client):
    lead = LeadFactory()
    _auth(api_client)
    api_client.post(f"/api/v1/leads/{lead.id}/note/", {"body": "A note."}, format="json")
    detail = api_client.get(f"/api/v1/leads/{lead.id}/").json()
    assert len(detail["notes"]) == 1
    assert detail["notes"][0]["body"] == "A note."
