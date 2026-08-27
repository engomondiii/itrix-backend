"""
The shell contract (Backend v7.1 §Phase 1, Architecture v2.8 §11.6).

``shell.for_subject`` is the single authority for what Surface 1 may render. These tests
pin the rules that make it load-bearing rather than decorative.

── v7.1 REWROTE THE ZONE ASSERTIONS, AND THAT IS THE POINT ─────────────────
The v6.0 version of this file asserted that ``sidebar_sections`` contained ``brand_nav``,
``explore`` and ``legal``. It no longer does, and the change is deliberate: the one
vocabulary split into two, and ``sidebar_sections`` is now an ALIAS OF THE RAIL for one
release.

Everything that is NOT about the zones — the ceiling rule, the composer labels, the
retired rails, the null next-best-action — is preserved verbatim, because none of it
changed.
"""

from __future__ import annotations

import pytest

from apps.journey.constants_zones import (
    BASE_PANE_SECTIONS,
    CONVERSATION_RAIL_SECTIONS,
    PANE_SECTIONS,
    RAIL_SECTIONS,
    SHELL_MODE_ARRIVAL,
    SHELL_MODE_WORKING,
    UnknownZoneSection,
    validate_pane_sections,
    validate_rail_sections,
)
from apps.journey.services import shell
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def _visitor_turn(thread, body: str = "Our solver is slow.", seq: int = 1):
    """
    A visitor turn on ``thread``.

    ``Message.conversation`` is NOT NULL, so a bare ``Message.objects.create(thread=...)``
    fails at the database. The Thread the service reads and the Conversation the Message
    requires are two different models in this schema — a distinction easy to miss until the
    integrity error, which is exactly why this helper exists in one place.
    """
    from apps.conversations.models import Message, SenderKind
    from tests.factories.conversation_factory import ConversationFactory

    conversation = thread.conversation or ConversationFactory(lead=thread.lead)
    if thread.conversation_id != conversation.id:
        thread.conversation = conversation
        thread.save(update_fields=["conversation"])

    return Message.objects.create(
        conversation=conversation,
        thread=thread,
        sender_kind=SenderKind.VISITOR,
        body=body,
        seq=seq,
    )


def _confirmed_customer_thread(lead, *, session="sess-shell-confirmed"):
    """Create the active thread needed to satisfy the STR-03 recommendation gate."""
    from apps.conversations.services import engagement_state, threads as thread_svc

    thread = thread_svc.create_thread(visitor_session=session, lead=lead)
    thread.relationship_state = engagement_state.REL_CUSTOMER
    thread.mirror_status = engagement_state.MIRROR_CONFIRMED
    thread.save(update_fields=["relationship_state", "mirror_status", "updated_at"])
    return thread


# ─────────────────────────────────────────────────────────────────────────────
# Preserved from v6.0 — none of this changed
# ─────────────────────────────────────────────────────────────────────────────
def test_rails_are_absent_from_the_contract():
    """left_rail / right_rail are RETIRED. Their presence would be a regression."""
    lead = LeadFactory(journey_state="ASSESSMENT")
    contract = shell.for_subject(lead)
    assert "left_rail" not in contract
    assert "right_rail" not in contract


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
    """A state can NARROW the ceiling; it can never widen the plane's."""
    lead = LeadFactory(journey_state="CUSTOMER_SUCCESS", email="")
    contract = shell.for_subject(lead, identity_state="anonymous")
    assert contract["disclosure_ceiling"] in ("public", "controlled_public")


def test_next_best_action_now_passes_through_the_precedence_rule():
    """
    ── UPDATED BY v7.1 PHASE 3 ─────────────────────────────────────────────
    This test used to assert ``next_best_action is None``, which was correct while the portal
    path had no rule wired to it. Phase 3 wires it, so the assertion becomes the one that
    actually matters: whatever comes out, it came through ``nba_precedence``.

    The key property is NEGATIVE and is pinned separately below — a commercial action must
    never be primary while a suppression condition holds. §18.7 calls that a defect, not a
    judgement call.
    """
    lead = LeadFactory(journey_state="ASSESSMENT", email="x@example.com")
    action = shell.for_subject(lead)["next_best_action"]
    # Either a governed action or None. Never a raw candidate dict with internal fields.
    assert action is None or set(action.keys()) <= {"key", "label", "detail", "href"}


def test_the_client_payload_never_carries_a_suppression_reason():
    """
    §10.5. A customer does not need to be told we decided not to sell to them today, and
    telling them would be a strange kind of honesty — it would surface a commercial
    deliberation they never asked to be part of.
    """
    lead = LeadFactory(journey_state="CUSTOMER_SUCCESS", email="x@example.com")
    action = shell.for_subject(lead)["next_best_action"]
    if action is not None:
        for forbidden in ("suppressionReason", "suppression_reason", "signals", "kind", "weight"):
            assert forbidden not in action


def test_the_portal_and_the_cockpit_reach_the_same_decision():
    """
    §11.1: one rule, both planes. If it were implemented twice they would drift, and the first
    symptom would be a customer being sold to while their operator looked at an unresolved
    outage.
    """
    from apps.agents.services.strategy import nba_candidates
    from apps.governance.services import nba_precedence

    lead = LeadFactory(journey_state="ASSESSMENT", email="x@example.com")
    thread = _confirmed_customer_thread(lead)
    portal = shell.for_subject(lead, thread=thread)["next_best_action"]
    cockpit = nba_precedence.for_lead(lead, nba_candidates(lead)).to_client_payload()
    assert portal == cockpit


# ─────────────────────────────────────────────────────────────────────────────
# v7.1 — the conversation rail NEVER GROWS
# ─────────────────────────────────────────────────────────────────────────────
def test_rail_is_three_keys_at_every_state():
    """
    The rail's job is to name conversations. In v6.0 the sidebar gained a section per
    state and carried fourteen by State 10, which made it a navigation menu that happened
    to contain conversations.
    """
    for state in ("ARRIVED", "IN_REVIEW", "CLIENT_PAGE", "NDA_REVIEW",
                  "ASSESSMENT", "POC", "INTEGRATION", "CUSTOMER_SUCCESS", "DORMANT"):
        lead = LeadFactory(journey_state=state, email="x@example.com")
        rail = shell.for_subject(lead)["conversation_rail_sections"]
        assert rail == list(CONVERSATION_RAIL_SECTIONS), f"rail grew at {state}: {rail}"


def test_rail_is_not_suppressed_on_the_anonymous_plane():
    """
    The three rail sections are ORIENTATION, not entitlement. A visitor with no
    relationship still needs a way to start a conversation and find the ones they have,
    and none of the three can name an organisation.
    """
    lead = LeadFactory(journey_state="ARRIVED", email="")
    rail = shell.for_subject(lead, identity_state="anonymous")["conversation_rail_sections"]
    assert rail == list(CONVERSATION_RAIL_SECTIONS)


def test_retired_sidebar_keys_never_appear_in_the_rail():
    """brand_nav, explore, legal and new_review left the rail. None may come back."""
    lead = LeadFactory(journey_state="CUSTOMER_SUCCESS", email="x@example.com")
    rail = shell.for_subject(lead)["conversation_rail_sections"]
    for retired in ("brand_nav", "new_review", "explore", "legal", "documents", "outcomes"):
        assert retired not in rail


# ─────────────────────────────────────────────────────────────────────────────
# v7.1 — the content pane is the zone that grows
# ─────────────────────────────────────────────────────────────────────────────
def test_pane_base_sections_are_present_at_every_state():
    """
    ``explore`` and ``legal`` resolve at every state and on every plane. ``legal`` is not
    optional: the four instruments are "not permitted to disappear at any width" (§2.4).
    """
    for state in ("ARRIVED", "IN_REVIEW", "DIAGNOSED", "CUSTOMER_SUCCESS", "DORMANT"):
        for identity in ("anonymous", "identified"):
            lead = LeadFactory(journey_state=state, email="x@example.com")
            pane = shell.for_subject(lead, identity_state=identity)["content_pane_sections"]
            for key in BASE_PANE_SECTIONS:
                assert key in pane, f"{key} missing at {state}/{identity}"


def test_pane_grows_monotonically_across_the_ladder():
    counts = []
    for state in ("ARRIVED", "IN_REVIEW", "CLIENT_PAGE", "NDA_REVIEW",
                  "ASSESSMENT", "POC", "INTEGRATION", "CUSTOMER_SUCCESS"):
        lead = LeadFactory(journey_state=state, email="x@example.com")
        counts.append(len(shell.for_subject(lead)["content_pane_sections"]))
    assert counts == sorted(counts), f"pane section count must be monotonic: {counts}"


def test_anonymous_suppresses_every_organisation_revealing_pane_section():
    """
    Carried forward from v6.0 unchanged in substance: anonymous suppresses these AT ANY
    STATE, including a state the subject should never have reached anonymously.
    """
    lead = LeadFactory(journey_state="ASSESSMENT", email="")
    contract = shell.for_subject(lead, identity_state="anonymous")
    assert contract["identity_state"] == "anonymous"
    for forbidden in ("documents", "workspace_assessment", "decisions", "nda",
                      "outcomes", "support", "governance"):
        assert forbidden not in contract["content_pane_sections"]


def test_identified_subject_sees_workspace_pane_sections():
    lead = LeadFactory(journey_state="ASSESSMENT", email="someone@example.com")
    pane = shell.for_subject(lead)["content_pane_sections"]
    assert "workspace_assessment" in pane
    assert "decisions" in pane


def test_every_emitted_pane_section_is_in_the_closed_vocabulary():
    for state in ("ARRIVED", "NDA_REVIEW", "ASSESSMENT", "POC",
                  "INTEGRATION", "CUSTOMER_SUCCESS"):
        lead = LeadFactory(journey_state=state, email="x@example.com")
        for key in shell.for_subject(lead)["content_pane_sections"]:
            assert key in PANE_SECTIONS, f"{key} is outside the closed vocabulary"


def test_unknown_section_key_is_a_server_error_not_a_silent_skip():
    """A typo must fail loudly rather than quietly hiding an entitled section."""
    with pytest.raises(UnknownZoneSection):
        validate_rail_sections(["new_chat", "not_a_real_section"])
    with pytest.raises(UnknownZoneSection):
        validate_pane_sections(["artifacts", "not_a_real_section"])


def test_a_pane_key_is_not_a_rail_key_and_vice_versa():
    """
    The two vocabularies overlap in exactly one place — ``conversations`` is a rail key and
    is NOT a pane key — and nothing else is shared. A key in both would let a section
    render in two zones.
    """
    assert RAIL_SECTIONS.isdisjoint(PANE_SECTIONS)


# ─────────────────────────────────────────────────────────────────────────────
# v7.1 — the one-release alias
# ─────────────────────────────────────────────────────────────────────────────
def test_the_sidebar_sections_alias_is_gone():
    """
    ── UPDATED BY v7.1 PHASE 3 ─────────────────────────────────────────────
    The alias was the RAIL — never the union of both zones, because emitting the union would
    have put pane sections back into a sidebar on an un-migrated client. It survived Phases 1
    and 2 so both frontends had a full release to migrate.

    They have. Both read ``conversation_rail_sections`` now, so the alias had no readers left,
    and keeping a field nobody reads only invites a new reader.
    """
    lead = LeadFactory(journey_state="CUSTOMER_SUCCESS", email="x@example.com")
    contract = shell.for_subject(lead)
    assert "sidebar_sections" not in contract
    assert contract["conversation_rail_sections"] == list(CONVERSATION_RAIL_SECTIONS)


def test_the_anonymous_thread_contract_has_no_alias_either():
    from apps.conversations.services import threads as thread_svc

    thread = thread_svc.create_thread(visitor_session="sess-no-alias")
    assert "sidebar_sections" not in shell.for_anonymous_thread(thread)


# ─────────────────────────────────────────────────────────────────────────────
# v7.1 — shell_mode is DERIVED, and arrival is the fail-safe
# ─────────────────────────────────────────────────────────────────────────────
def test_shell_mode_is_arrival_with_no_thread():
    lead = LeadFactory(journey_state="ARRIVED")
    assert shell.for_subject(lead)["shell_mode"] == SHELL_MODE_ARRIVAL


def test_shell_mode_is_arrival_for_an_empty_thread():
    """A thread exists but nothing has been said in it. The front door is correct."""
    from apps.conversations.services import threads as thread_svc

    thread = thread_svc.create_thread(visitor_session="sess-mode-empty")
    assert shell.for_anonymous_thread(thread)["shell_mode"] == SHELL_MODE_ARRIVAL


def test_shell_mode_becomes_working_on_the_first_visitor_turn():
    """
    THE THRESHOLD IS THE VISITOR'S OWN SENTENCE, not the journey state. State can lag a
    turn behind, and showing the bare front door with the visitor's words already on
    screen would be wrong.
    """
    from apps.conversations.services import threads as thread_svc

    thread = thread_svc.create_thread(visitor_session="sess-mode-spoken")
    _visitor_turn(thread)
    assert shell.for_anonymous_thread(thread)["shell_mode"] == SHELL_MODE_WORKING


def test_an_assistant_turn_alone_does_not_make_it_working():
    """
    Only a VISITOR turn crosses the threshold. A thread that somehow held only an
    assistant message is not a conversation the visitor has started.
    """
    from apps.conversations.models import Message, SenderKind
    from apps.conversations.services import threads as thread_svc
    from tests.factories.conversation_factory import ConversationFactory

    thread = thread_svc.create_thread(visitor_session="sess-mode-agent-only")
    conversation = thread.conversation or ConversationFactory(lead=thread.lead)
    thread.conversation = conversation
    thread.save(update_fields=["conversation"])
    Message.objects.create(
        conversation=conversation, thread=thread,
        sender_kind=SenderKind.AGENT, body="Hello.", seq=1,
    )
    assert shell.for_anonymous_thread(thread)["shell_mode"] == SHELL_MODE_ARRIVAL


# ─────────────────────────────────────────────────────────────────────────────
# v7.1 — the default artifact
# ─────────────────────────────────────────────────────────────────────────────
def test_default_artifact_is_none_without_an_artifacts_section():
    """A default for a section the subject cannot see is a default that cannot be honoured."""
    lead = LeadFactory(journey_state="ARRIVED")
    contract = shell.for_subject(lead)
    assert "artifacts" not in contract["content_pane_sections"]
    assert contract["content_pane_default_artifact_id"] is None


def test_anonymous_thread_contract_is_minimum_privilege():
    from apps.conversations.services import threads as thread_svc

    thread = thread_svc.create_thread(visitor_session="sess-abc")
    contract = shell.for_anonymous_thread(thread)
    assert contract["journey_state"] == 1
    assert contract["disclosure_ceiling"] == "public"
    assert contract["identity_state"] == "anonymous"
    assert contract["conversation_rail_sections"] == list(CONVERSATION_RAIL_SECTIONS)
    assert set(contract["content_pane_sections"]) == set(BASE_PANE_SECTIONS)
    assert contract["conversation_header"]["quick_help"] is False
    # No Lead exists yet, so there is no subject the precedence rule could reason about.
    assert contract["next_best_action"] is None
