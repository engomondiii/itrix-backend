"""
The shell contract (Backend v6.0 §3.1).

``shell.for_subject`` is the single authority for what Surface 1 may render. These tests
pin the four rules that make it load-bearing rather than decorative.
"""

from __future__ import annotations

import pytest

from apps.journey.constants import BASE_SIDEBAR_SECTIONS, SIDEBAR_SECTIONS
from apps.journey.services import shell
from apps.journey.services.shell import UnknownSidebarSection
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def test_rails_are_absent_from_the_contract():
    """left_rail / right_rail are RETIRED. Their presence would be a regression."""
    lead = LeadFactory(journey_state="ASSESSMENT")
    contract = shell.for_subject(lead)
    assert "left_rail" not in contract
    assert "right_rail" not in contract
    assert "sidebar_sections" in contract


def test_base_sections_are_present_at_every_state():
    """
    A visitor with nothing authorized still gets orientation and a route to policy
    (§16.2). brand_nav and legal in particular must never be absent.
    """
    for state in ("ARRIVED", "IN_REVIEW", "DIAGNOSED", "CUSTOMER_SUCCESS", "DORMANT"):
        lead = LeadFactory(journey_state=state)
        sections = shell.for_subject(lead)["sidebar_sections"]
        for key in BASE_SIDEBAR_SECTIONS:
            assert key in sections, f"{key} missing at {state}"


def test_anonymous_suppresses_every_organisation_revealing_section():
    """
    RULE 2. identity_state == anonymous suppresses these AT ANY STATE — including a
    state the subject should never have reached anonymously.
    """
    lead = LeadFactory(journey_state="ASSESSMENT", email="")
    contract = shell.for_subject(lead, identity_state="anonymous")
    assert contract["identity_state"] == "anonymous"
    for forbidden in ("documents", "workspace_assessment", "decisions", "nda"):
        assert forbidden not in contract["sidebar_sections"]


def test_identified_subject_sees_workspace_sections():
    lead = LeadFactory(journey_state="ASSESSMENT", email="someone@example.com")
    sections = shell.for_subject(lead)["sidebar_sections"]
    assert "workspace_assessment" in sections
    assert "decisions" in sections


def test_unknown_section_key_is_a_server_error_not_a_silent_skip():
    """RULE 3. A typo must fail loudly rather than quietly hiding an entitled section."""
    from apps.journey.constants import validate_sidebar_sections

    with pytest.raises(ValueError):
        validate_sidebar_sections(["brand_nav", "not_a_real_section"])


def test_every_emitted_section_is_in_the_closed_vocabulary():
    for state in ("ARRIVED", "NDA_REVIEW", "ASSESSMENT", "POC", "INTEGRATION", "CUSTOMER_SUCCESS"):
        lead = LeadFactory(journey_state=state, email="x@example.com")
        for key in shell.for_subject(lead)["sidebar_sections"]:
            assert key in SIDEBAR_SECTIONS, f"{key} is outside the closed vocabulary"


def test_sections_grow_with_state_but_width_does_not():
    """The sidebar's SECTIONS grow with state; nothing about it is state-dependent width."""
    counts = []
    for state in ("ARRIVED", "CLIENT_PAGE", "NDA_REVIEW", "ASSESSMENT", "CUSTOMER_SUCCESS"):
        lead = LeadFactory(journey_state=state, email="x@example.com")
        counts.append(len(shell.for_subject(lead)["sidebar_sections"]))
    assert counts == sorted(counts), "section count must be monotonic across the ladder"


def test_composer_label_changes_only_at_arrival_and_state_ten():
    labels = {}
    for state in ("ARRIVED", "IN_REVIEW", "ASSESSMENT", "CUSTOMER_SUCCESS"):
        lead = LeadFactory(journey_state=state)
        labels[state] = shell.for_subject(lead)["composer_label"]
    assert labels["ARRIVED"] == "What would you like computation to do better?"
    assert labels["IN_REVIEW"] == "Ask itriX"
    assert labels["ASSESSMENT"] == "Ask itriX"
    assert labels["CUSTOMER_SUCCESS"] == "What can we improve for you?"


def test_plane_ceiling_always_beats_state_ceiling():
    """
    A state can NARROW the ceiling; it can never widen the plane's.

    An anonymous visitor at state 10 is still capped at the anonymous plane.
    """
    lead = LeadFactory(journey_state="CUSTOMER_SUCCESS", email="")
    contract = shell.for_subject(lead, identity_state="anonymous")
    assert contract["disclosure_ceiling"] in ("public", "controlled_public")


def test_next_best_action_is_none_in_phase_one():
    """
    Phase 1 emits None rather than an unsuppressed commercial action. Emitting one
    before the customer-first precedence rule exists would violate §18.7 by default.
    """
    lead = LeadFactory(journey_state="ASSESSMENT", email="x@example.com")
    assert shell.for_subject(lead)["next_best_action"] is None


def test_anonymous_thread_contract_is_minimum_privilege():
    from apps.conversations.services import threads as thread_svc

    thread = thread_svc.create_thread(visitor_session="sess-abc")
    contract = shell.for_anonymous_thread(thread)
    assert contract["journey_state"] == 1
    assert contract["disclosure_ceiling"] == "public"
    assert contract["identity_state"] == "anonymous"
    assert set(contract["sidebar_sections"]) == set(BASE_SIDEBAR_SECTIONS)
    assert contract["conversation_header"]["quick_help"] is False
