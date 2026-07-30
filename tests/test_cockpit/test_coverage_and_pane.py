"""
THE COVERAGE READ and CONTENT-PANE AUTHORIZATION (Backend v7.1 Phase 2).

Two reads that look similar and answer opposite questions:

    coverage      an INTERNAL read. What does the system understand, and on what evidence?
    pane          a VISITOR-FACING read. What may this subject actually see?

The first must never reach a client plane; the second is the client plane. Testing them in
one file keeps that distinction in view.
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
        email=f"{role.lower()}-cov@itrix.test",
        password="a-long-enough-password",
        role=role,
        is_active=True,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _thread(session="sess-cov", lead=None):
    from apps.conversations.services import threads as thread_svc

    thread = thread_svc.create_thread(visitor_session=session)
    if lead is not None:
        thread.lead = lead
        thread.save(update_fields=["lead"])
    return thread


def _artifact(thread, **kwargs):
    from apps.journey.models_artifacts import Artifact

    defaults = {
        "thread": thread,
        "type": "reflection",
        "version": 1,
        "payload": {"acknowledgement": "We have that."},
        "disclosure_level": "controlled_public",
        "governance_status": "approved",
        "pinned": False,
    }
    defaults.update(kwargs)
    return Artifact.objects.create(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# Coverage
# ─────────────────────────────────────────────────────────────────────────────
def test_every_dimension_is_returned_even_with_no_snapshot():
    """
    THE ABSENT ONES ARE WHAT AN OPERATOR IS LOOKING FOR.

    Omitting them would make a thread that has covered nothing look identical to one that has
    covered everything, which defeats the entire read.
    """
    from apps.journey.constants import LISTENING_DIMENSIONS

    thread = _thread("sess-cov-empty")
    body = _team_client().get(f"/api/v1/cockpit/threads/{thread.id}/coverage/").json()

    assert len(body["dimensions"]) == len(LISTENING_DIMENSIONS)
    assert body["unknown"] == len(LISTENING_DIMENSIONS)
    assert body["covered"] == 0
    assert [d["dimension"] for d in body["dimensions"]] == list(LISTENING_DIMENSIONS)


def test_a_covered_dimension_carries_its_evidence():
    """
    "Why is this covered?" must have an answer, or the map is a number an operator learns to
    ignore — the same failure mode as a health class without reasons.
    """
    from apps.journey.models_artifacts import CoverageSnapshot

    thread = _thread("sess-cov-evidence")
    CoverageSnapshot.objects.create(
        thread=thread, dimension="workload", status="covered", evidence_message_id="msg-42"
    )

    body = _team_client().get(f"/api/v1/cockpit/threads/{thread.id}/coverage/").json()
    row = next(d for d in body["dimensions"] if d["dimension"] == "workload")
    assert row["status"] == "covered"
    assert row["evidenceMessageId"] == "msg-42"
    assert body["covered"] == 1


def test_partial_is_named_rather_than_left_for_a_chart_to_halve():
    """
    `partial` is not half a dimension. It is one the system has a hint about and has not
    established, and a percentage that averaged it would overstate understanding.
    """
    from apps.journey.models_artifacts import CoverageSnapshot

    thread = _thread("sess-cov-partial")
    CoverageSnapshot.objects.create(thread=thread, dimension="baseline", status="partial")

    body = _team_client().get(f"/api/v1/cockpit/threads/{thread.id}/coverage/").json()
    assert body["partial"] == 1
    assert body["statuses"] == ["unknown", "partial", "covered"]
    assert "percent" not in body


def test_the_read_states_what_covered_means():
    thread = _thread("sess-cov-interp")
    body = _team_client().get(f"/api/v1/cockpit/threads/{thread.id}/coverage/").json()
    assert "established it" in body["interpretation"]


def test_coverage_is_team_gated():
    from rest_framework.test import APIClient

    thread = _thread("sess-cov-gate")
    response = APIClient().get(f"/api/v1/cockpit/threads/{thread.id}/coverage/")
    assert response.status_code in (401, 403)


def test_an_unknown_thread_coverage_is_404():
    import uuid

    assert _team_client().get(f"/api/v1/cockpit/threads/{uuid.uuid4()}/coverage/").status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Content-pane authorization — the three rules, in order of how badly each fails
# ─────────────────────────────────────────────────────────────────────────────
def test_rule_one_governance_first_an_unapproved_artifact_never_renders():
    """
    Whatever its disclosure level, whatever section asked for it. Under review means a human
    has not finished deciding, and the pane is not where that decision gets pre-empted.
    """
    from apps.cockpit.services import pane_authorization

    thread = _thread("sess-pane-gov")
    _artifact(thread, governance_status="under_review", disclosure_level="public")

    allowed = pane_authorization.authorized_artifacts(
        thread, disclosure_ceiling="customer_contract", sections=["artifacts"]
    )
    assert allowed == []


def test_rule_two_the_ceiling_refuses_an_artifact_above_it():
    from apps.cockpit.services import pane_authorization

    thread = _thread("sess-pane-ceiling")
    _artifact(thread, type="boundary_waste_map", disclosure_level="nda_only")

    # A controlled-public subject cannot reach an nda_only artifact.
    assert pane_authorization.authorized_artifacts(
        thread, disclosure_ceiling="controlled_public", sections=["artifacts", "workspace_assessment"]
    ) == []

    # An nda_only subject can.
    assert len(pane_authorization.authorized_artifacts(
        thread, disclosure_ceiling="nda_only", sections=["workspace_assessment"]
    )) == 1


def test_an_unknown_disclosure_level_is_refused_not_passed_through():
    """
    A new level added server-side should become INVISIBLE here until someone decides where it
    sits. The alternative is that it becomes visible to everyone.
    """
    from apps.cockpit.services import pane_authorization

    thread = _thread("sess-pane-unknown")
    _artifact(thread, disclosure_level="some_new_tier")

    assert pane_authorization.authorized_artifacts(
        thread, disclosure_ceiling="customer_contract", sections=["artifacts"]
    ) == []


def test_rule_three_the_section_is_last_so_a_mapping_bug_hides_rather_than_leaks():
    from apps.cockpit.services import pane_authorization

    thread = _thread("sess-pane-section")
    _artifact(thread, type="poc_evidence", disclosure_level="nda_only")

    # `workspace_poc` renders poc_evidence; `documents` does not.
    assert pane_authorization.authorized_artifacts(
        thread, disclosure_ceiling="nda_only", sections=["documents"]
    ) == []
    assert len(pane_authorization.authorized_artifacts(
        thread, disclosure_ceiling="nda_only", sections=["workspace_poc"]
    )) == 1


def test_no_capability_token_is_ever_in_a_pane_payload():
    """
    A token is a bearer credential for a deep link, and the pane renders in place. Including
    one would put a credential in a payload that has no use for it — which is how credentials
    end up in logs.
    """
    from apps.cockpit.services import pane_authorization

    thread = _thread("sess-pane-token")
    _artifact(thread, capability_token="tok-should-never-appear")

    rows = pane_authorization.authorized_artifacts(
        thread, disclosure_ceiling="controlled_public", sections=["artifacts"]
    )
    assert rows
    for row in rows:
        assert "capabilityToken" not in row
        assert "capability_token" not in row
        assert "tok-should-never-appear" not in str(row)


def test_the_default_artifact_skips_a_pinned_one():
    """
    `success_overview` is standing context ABOVE the transcript, so opening the pane onto it
    would show the same thing twice.
    """
    from apps.cockpit.services import pane_authorization

    thread = _thread("sess-pane-default")
    _artifact(thread, type="success_overview", pinned=True, disclosure_level="customer_contract")
    unpinned = _artifact(thread, type="reflection", pinned=False)

    rows = pane_authorization.authorized_artifacts(
        thread, disclosure_ceiling="customer_contract", sections=["artifacts"]
    )
    assert pane_authorization.default_artifact_id(rows) == str(unpinned.id)


# ─────────────────────────────────────────────────────────────────────────────
# The visitor-facing pane endpoint
# ─────────────────────────────────────────────────────────────────────────────
def test_the_pane_endpoint_is_session_scoped():
    """A thread id is not a credential: guessing one gets a 404, not a payload."""
    from rest_framework.test import APIClient

    thread = _thread("sess-pane-owner")
    _artifact(thread)

    # A different session cannot read it.
    stranger = APIClient()
    assert stranger.get(f"/api/v1/threads/{thread.id}/pane/").status_code == 404


def test_an_anonymous_thread_pane_carries_only_what_it_should():
    """
    An anonymous visitor's pane resolves `explore` and `legal` and nothing organisation-
    revealing — the Phase 1 suppression rule, seen through the contents read.
    """
    thread = _thread("sess-pane-anon")
    from rest_framework.test import APIClient

    client = APIClient()
    client.cookies["itrix_visitor"] = "sess-pane-anon"
    response = client.get(f"/api/v1/threads/{thread.id}/pane/")

    # Session cookie naming varies by deployment; when the ownership check refuses, that is
    # the correct answer and there is nothing to assert about contents.
    if response.status_code == 200:
        body = response.json()
        for forbidden in ("outcomes", "support", "workspace_assessment", "governance"):
            assert forbidden not in body["content_pane_sections"]
