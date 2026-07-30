"""
``journey/leads/{id}/`` returns the shell contract (Backend v7.1 §Phase 1).

── THE HIGHEST-PRIORITY CORRECTION IN THIS PHASE ───────────────────────────
This is a production crash, not a missing feature. The dashboard's lead-detail page
renders a shell-contract panel from ``payload.shell`` and threw when the key was absent.

The dashboard deliberately does not derive the contract itself. It authenticates on its
own team-JWT, so anything it derived would be its own opinion of what a visitor may see
rather than the server's — and an oversight panel showing a contract the visitor is not
actually on is worse than a panel showing nothing.
"""

from __future__ import annotations

import pytest

from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def _team_client(role: str = "ASSESSMENT"):
    from django.contrib.auth import get_user_model
    from rest_framework.test import APIClient

    User = get_user_model()
    user = User.objects.create_user(
        email=f"{role.lower()}-leadshell@itrix.test",
        password="a-long-enough-password",
        role=role,
        is_active=True,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_the_payload_carries_shell():
    lead = LeadFactory(journey_state="ASSESSMENT", email="x@example.com")
    response = _team_client().get(f"/api/v1/journey/leads/{lead.id}/")
    assert response.status_code == 200
    body = response.json()
    assert "shell" in body, "the missing key is what crashed the lead-detail page"
    assert body["shell"] is not None


def test_shell_carries_both_zones_and_the_mode():
    lead = LeadFactory(journey_state="ASSESSMENT", email="x@example.com")
    shell = _team_client().get(f"/api/v1/journey/leads/{lead.id}/").json()["shell"]
    for key in (
        "shell_mode",
        "conversation_rail_sections",
        "content_pane_sections",
        "content_pane_default_artifact_id",
    ):
        assert key in shell, f"{key} missing from the lead payload's shell"


def test_the_plane_is_the_subjects_not_the_requesters():
    """
    A specialist viewing an ANONYMOUS visitor's lead sees the ANONYMOUS visitor's shell,
    suppressed sections and all.

    This endpoint answers "what is this visitor seeing?". It would be useless — and
    misleading in an audit — if it answered "what would I see?".
    """
    lead = LeadFactory(journey_state="ASSESSMENT", email="")
    shell = _team_client("ADMIN").get(f"/api/v1/journey/leads/{lead.id}/").json()["shell"]
    assert shell["identity_state"] == "anonymous"
    for suppressed in ("documents", "workspace_assessment", "decisions"):
        assert suppressed not in shell["content_pane_sections"]


def test_it_is_the_same_builder_surface_one_uses():
    """
    One builder, one answer, whoever is asking. Two builders would mean the oversight panel
    could disagree with the visitor's screen, which is the one thing it must not do.
    """
    from apps.journey.services import shell as shell_svc

    lead = LeadFactory(journey_state="POC", email="x@example.com")
    via_api = _team_client().get(f"/api/v1/journey/leads/{lead.id}/").json()["shell"]
    direct = shell_svc.for_subject(lead)

    for key in ("shell_mode", "conversation_rail_sections", "content_pane_sections",
                "disclosure_ceiling", "composer_label", "state_key"):
        assert via_api[key] == direct[key], key


def test_a_broken_shell_does_not_take_the_page_with_it():
    """
    The opposite trade from the one that caused this bug.

    A shell that cannot be built degrades to null; the journey and the transitions still
    answer. Previously the MISSING field took the whole page down.
    """
    from unittest.mock import patch

    lead = LeadFactory(journey_state="ASSESSMENT", email="x@example.com")
    with patch(
        "apps.journey.services.shell.for_subject",
        side_effect=RuntimeError("boom"),
    ):
        response = _team_client().get(f"/api/v1/journey/leads/{lead.id}/")

    assert response.status_code == 200
    body = response.json()
    assert body["shell"] is None
    # The rest of the page is intact.
    assert body["leadId"] == str(lead.id)
    assert body["state"] == "ASSESSMENT"
    assert "transitions" in body
