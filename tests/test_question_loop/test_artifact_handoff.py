"""
The stop-rule handoff to artifact generation (Backend v6.0 §5.5).

    When the stop rule fires for the qualification band, artifacts.generate(thread,
    "reflection") runs, then the pitch room, then journey.advance().
    NO FURTHER QUESTION IS ASKED.
"""

from __future__ import annotations

import pytest

from apps.journey.constants import ARTIFACT_PITCH_ROOM, ARTIFACT_REFLECTION
from apps.journey.models_artifacts import Artifact
from apps.journey.services import artifacts

pytestmark = pytest.mark.django_db


@pytest.fixture
def lead_thread(db):
    from apps.conversations.services import threads as thread_svc
    from tests.factories.lead_factory import LeadFactory

    lead = LeadFactory(journey_state="IN_REVIEW", tier=1)
    return lead, thread_svc.create_thread(visitor_session="s-art", lead=lead)


def test_a_reflection_is_generated(lead_thread):
    _lead, thread = lead_thread
    artifact = artifacts.generate(thread, ARTIFACT_REFLECTION, force=True)
    assert artifact.type == ARTIFACT_REFLECTION
    assert artifact.version == 1


def test_regeneration_supersedes_rather_than_overwrites(lead_thread):
    """
    The earlier version is what the customer READ. Both need to exist.
    """
    _lead, thread = lead_thread
    first = artifacts.generate(thread, ARTIFACT_REFLECTION, force=True)
    second = artifacts.generate(thread, ARTIFACT_REFLECTION, force=True)

    first.refresh_from_db()
    assert first.superseded_by_id == second.id
    assert second.version == 2
    assert Artifact.objects.filter(thread=thread, type=ARTIFACT_REFLECTION).count() == 2


def test_only_the_current_version_is_listed(lead_thread):
    _lead, thread = lead_thread
    artifacts.generate(thread, ARTIFACT_REFLECTION, force=True)
    artifacts.generate(thread, ARTIFACT_REFLECTION, force=True)
    current = artifacts.for_thread(thread, ceiling="public")
    assert len(current) == 1
    assert current[0].version == 2


def test_a_state_cannot_receive_an_unauthorized_artifact(lead_thread):
    """State 2 has no business producing a Boundary Waste Map."""
    _lead, thread = lead_thread
    from apps.journey.constants import ARTIFACT_BOUNDARY_WASTE_MAP

    with pytest.raises(artifacts.ArtifactNotAuthorized):
        artifacts.generate(thread, ARTIFACT_BOUNDARY_WASTE_MAP)


def test_an_unknown_artifact_type_is_a_server_error(lead_thread):
    _lead, thread = lead_thread
    with pytest.raises(ValueError):
        artifacts.generate(thread, "not_a_real_artifact", force=True)


def test_the_pitch_room_token_grants_reach_to_the_artifact_only(lead_thread):
    """
    An artifact token grants reach to that artifact's read endpoint — never the ability
    to post a turn to the thread that produced it (§3.3).
    """
    _lead, thread = lead_thread
    artifact = artifacts.generate(thread, ARTIFACT_PITCH_ROOM, force=True)
    token = artifacts.bind_capability_token(artifact)
    artifact.refresh_from_db()
    assert artifact.capability_token == token

    from apps.journey.services import capability_token as ct

    payload = ct.verify(token)
    assert payload.state.startswith("artifact:")


def test_the_boundary_waste_map_has_no_numeric_field(lead_thread):
    """
    STRUCTURAL. A performance claim before a PoC is impossible here because the payload
    has nowhere to put a number.
    """
    _lead, thread = lead_thread
    payload = artifacts.build_payload(thread, "boundary_waste_map")

    def has_number(node) -> bool:
        if isinstance(node, (int, float)) and not isinstance(node, bool):
            return True
        if isinstance(node, dict):
            return any(has_number(v) for v in node.values())
        if isinstance(node, (list, tuple)):
            return any(has_number(v) for v in node)
        return False

    assert not has_number(payload), "the Boundary Waste Map must carry no numeric field"
    assert len(payload["sections"]) == 10


def test_kpi_outcomes_are_exactly_four_words():
    """
    "It is NEVER re-described after the fact as a partial success, a learning, or a
    promising signal. THE CREDIBILITY OF EVERY FUTURE CLAIM DEPENDS ON THIS ONE."
    """
    assert artifacts.KPI_OUTCOMES == ("pass", "partial", "negative", "pending")


@pytest.mark.parametrize("bad", ["promising", "partial success", "trending positive",
                                 "learning", "inconclusive but encouraging"])
def test_a_softened_kpi_outcome_is_refused(bad):
    with pytest.raises(ValueError):
        artifacts.validate_kpi_outcome(bad)


@pytest.mark.parametrize("good", ["pass", "partial", "negative", "pending"])
def test_the_four_approved_outcomes_are_accepted(good):
    assert artifacts.validate_kpi_outcome(good) == good


def test_the_success_overview_is_pinned(lead_thread):
    from apps.journey.constants import ARTIFACT_SUCCESS_OVERVIEW

    _lead, thread = lead_thread
    artifact = artifacts.generate(thread, ARTIFACT_SUCCESS_OVERVIEW, force=True)
    assert artifact.pinned is True
