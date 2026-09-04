"""Governed internal-champion artifacts.

Executive/Technical/Product briefs are Customer/Strategic Customer decision-support
artifacts.  They cannot be used by a Visitor, cannot bypass STR-03 confirmation, and
have closed structured payloads rather than an arbitrary JSON dump.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.conversations.services import engagement_state, ingest, threads as thread_svc
from apps.journey.constants import (
    ARTIFACT_EXECUTIVE_BRIEF,
    ARTIFACT_PRODUCT_BRIEF,
    ARTIFACT_TECHNICAL_BRIEF,
)
from apps.journey.services import artifacts
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def champion_thread():
    lead = LeadFactory(journey_state="CLIENT_PAGE", tier=1)
    thread = thread_svc.create_thread(visitor_session="champion-artifacts", lead=lead)
    thread.current_state = "CLIENT_PAGE"
    thread.relationship_state = engagement_state.REL_STRATEGIC_CUSTOMER
    thread.mirror_status = engagement_state.MIRROR_CONFIRMED
    thread.locale = "en"
    thread.save(update_fields=["current_state", "relationship_state", "mirror_status", "locale", "updated_at"])
    ingest.ingest_inbound(
        thread.conversation,
        sender_kind="visitor",
        body=(
            "We need to decide whether to scale our inference platform this year. "
            "Current p99 latency and power draw are constraining the product roadmap."
        ),
        thread=thread,
    )
    return thread


@pytest.mark.parametrize(
    "artifact_type,expected_keys",
    [
        (ARTIFACT_EXECUTIVE_BRIEF, {"kind", "title", "summary", "decision", "customerImpact", "evidenceNeeded", "risks", "recommendation"}),
        (ARTIFACT_TECHNICAL_BRIEF, {"kind", "title", "workload", "baseline", "observedPressures", "boundedHypothesis", "kpis", "proofPlan", "unknowns"}),
        (ARTIFACT_PRODUCT_BRIEF, {"kind", "title", "productContext", "userImpact", "tradeoffs", "evidenceNeeded", "deploymentImplications", "nextDecision"}),
    ],
)
def test_champion_payloads_have_closed_structured_schemas(champion_thread, artifact_type, expected_keys):
    payload = artifacts.build_payload(champion_thread, artifact_type)
    assert set(payload) == expected_keys
    assert payload["kind"] == artifact_type
    assert "json" not in " ".join(str(v).lower() for v in payload.values())


def test_visitor_cannot_generate_champion_artifact_even_at_an_authorized_numbered_state(champion_thread):
    champion_thread.relationship_state = engagement_state.REL_VISITOR
    champion_thread.save(update_fields=["relationship_state", "updated_at"])
    with pytest.raises(artifacts.ArtifactNotAuthorized):
        artifacts.generate(champion_thread, ARTIFACT_EXECUTIVE_BRIEF)


def test_customer_cannot_generate_champion_artifact_before_mirror_confirmation(champion_thread):
    champion_thread.mirror_status = engagement_state.MIRROR_PENDING
    champion_thread.save(update_fields=["mirror_status", "updated_at"])
    with pytest.raises(artifacts.ArtifactNotAuthorized):
        artifacts.generate(champion_thread, ARTIFACT_TECHNICAL_BRIEF)


def test_deliberately_skipped_mirror_is_an_explicit_allowed_path(champion_thread):
    champion_thread.mirror_status = engagement_state.MIRROR_SKIPPED
    champion_thread.save(update_fields=["mirror_status", "updated_at"])
    with patch("apps.journey.services.artifacts._govern", side_effect=lambda payload, _kind: (payload, "auto_approved")):
        artifact = artifacts.generate(champion_thread, ARTIFACT_PRODUCT_BRIEF)
    assert artifact.type == ARTIFACT_PRODUCT_BRIEF


def test_confidential_user_text_is_not_carried_into_champion_brief(champion_thread):
    ingest.ingest_inbound(
        champion_thread.conversation,
        sender_kind="visitor",
        body="Our unreleased internal project ZETA-847 runs at 713.42 watts; keep that confidential.",
        thread=champion_thread,
    )
    payload = artifacts.build_payload(champion_thread, ARTIFACT_EXECUTIVE_BRIEF)
    rendered = str(payload)
    assert "ZETA-847" not in rendered
    assert "713.42" not in rendered


def test_confidentiality_detector_failure_fails_closed_for_champion_source_text(champion_thread):
    with patch("apps.conversations.services.confidentiality.detect", side_effect=RuntimeError("detector unavailable")):
        payload = artifacts.build_payload(champion_thread, ARTIFACT_PRODUCT_BRIEF)
    # No user-provided sentence may survive when the safety decision cannot be made.
    assert payload["productContext"] == []
