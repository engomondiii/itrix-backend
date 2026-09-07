"""
#7, #11 and #12 — answering questions about itriX, recognising names, and knowing
enough before revealing a page.
"""

from __future__ import annotations

import pytest

from apps.ai_engine.services import entity_context
from apps.ai_engine.services.system_prompt_builder import (
    build_conversation_system_prompt,
    build_system_prompt,
)


def _prompt(question: str = "", chunks: list[dict] | None = None) -> str:
    return build_conversation_system_prompt(
        product_route="general",
        license_pathway=None,
        tier=4,
        pressures=[],
        chunks=chunks or [],
        context="public",
        question=question,
    )


# ── #7 · the conversational task ────────────────────────────────────────────


def test_the_conversation_prompt_does_not_carry_the_result_page_task():
    """
    The bug: the concierge used the result-page builder, whose TASK told the model to
    produce a diagnosis of the visitor's bottleneck. An ordinary question about the
    company had no room to be answered.
    """
    convo = _prompt("What is itriX?")

    assert "suitable for a public result page" not in convo
    assert "Answer the question the visitor actually asked" in convo


def test_the_conversation_prompt_licenses_identity_questions():
    convo = _prompt("What is itriX?")

    assert "general/company/technical-evaluator question" in convo
    assert "not a request to diagnose the visitor" in convo


def test_the_result_page_task_is_decision_support_for_its_own_callers():
    """Artifact generation keeps its own task, now governed by the full-conversation review contract."""
    page = build_system_prompt(
        product_route="general", license_pathway=None, tier=4, pressures=[], chunks=[]
    )

    assert "personalized decision-support review" in page
    assert "complete supplied conversation state" in page


def test_both_prompts_keep_the_claims_discipline_and_the_ceiling():
    convo = _prompt("What is itriX?")

    assert "GOVERNING RESPONSE RULES" in convo
    assert "this is a ceiling, not permission" in convo
    assert "no guarantees" in convo


# ── #11 · named entities ────────────────────────────────────────────────────


def test_elon_musk_resolves_to_his_organisations():
    found = entity_context.recognise("Would this be useful to Elon Musk?")

    assert [e.canonical for e in found] == ["Elon Musk"]
    assert set(found[0].organisations) == {"SpaceX", "Tesla", "xAI"}


@pytest.mark.parametrize("text", ["elon musk", "Musk", "ELON MUSK asked about this"])
def test_the_name_is_matched_case_insensitively(text):
    assert entity_context.recognise(text)


@pytest.mark.parametrize(
    "text",
    ["metadata about the run", "amdahl's law applies here", "we use appleseed internally"],
)
def test_a_name_inside_another_word_does_not_match(text):
    """`meta` must not fire inside `metadata`, nor `amd` inside `amdahl`."""
    assert entity_context.recognise(text) == []


def test_the_query_is_widened_with_the_relevant_workloads():
    """
    "Would this help Elon Musk?" embeds nothing about aerospace or autonomy, so it
    retrieves generic chunks. The expansion puts it near the material that answers it.
    """
    original = "Would this help Elon Musk?"
    widened = entity_context.expand_query(original)

    assert widened.startswith(original)  # the visitor's words come first
    assert "aerospace" in widened
    assert "autonomous driving" in widened.lower()




def test_streaming_and_non_streaming_share_the_same_entity_expansion_policy():
    """Live WebSocket answers must retrieve the same named-entity context as HTTP answers."""
    from apps.agents.services.concierge import ConciergeAgent

    widened = ConciergeAgent._retrieval_query("Would this be useful to Elon Musk?")
    assert "aerospace" in widened
    assert "autonomous driving" in widened.lower()

def test_an_unrecognised_message_is_left_exactly_as_it_was():
    text = "Our inference cost is climbing."
    assert entity_context.expand_query(text) == text
    assert entity_context.grounding_note(text) == ""


def test_the_grounding_note_reaches_the_prompt():
    convo = _prompt("Would this be useful to Elon Musk?")

    assert "RECOGNISED NAMES" in convo
    assert "SpaceX" in convo


def test_the_note_never_claims_a_relationship_and_never_assumes_identity():
    """
    The whole risk of an entity table is that it starts sounding like a customer list,
    or that it makes the model treat the visitor as the person they mentioned.
    """
    note = entity_context.grounding_note("What about Elon Musk?")

    assert "NOT state or imply that any named person or organisation is an itriX" in note
    assert "customer, prospect, partner or evaluator" in note
    assert "Do NOT assume the visitor works for" in note


def test_the_roadmap_claim_is_attributed_to_itrix_not_to_the_account():
    note = entity_context.grounding_note("Elon Musk")

    assert "itriX's own intentions and NOT about any existing relationship" in note


def test_recognition_order_is_stable():
    """Same entities, whatever order the visitor named them."""
    a = entity_context.recognise("Tesla and SpaceX")
    b = entity_context.recognise("SpaceX and Tesla")

    assert [e.canonical for e in a] == [e.canonical for e in b]


# ── #12 · knowing enough before the page ───────────────────────────────────


def test_five_dimensions_are_required_before_the_loop_closes():
    from apps.agents.services.coverage import REQUIRED_BY_STATE

    assert REQUIRED_BY_STATE[2] == (
        "workload",
        "pressure_area",
        "platform_environment",
        "scale",
        "timeline",
    )
    assert REQUIRED_BY_STATE[3] == REQUIRED_BY_STATE[2]


def test_one_good_opening_sentence_no_longer_closes_the_loop():
    """
    This is the reported case: a single sentence covered all three old dimensions, so
    the visitor reached the personalised page in two messages.
    """
    from apps.agents.services.coverage import CoverageMap, analyse_text

    opener = (
        "Our training and inference cost is rising faster than the value it creates, "
        "on a GPU cluster running PyTorch."
    )
    covered = CoverageMap(dimensions=analyse_text(opener))

    assert not covered.is_complete_for(2), "one sentence should no longer be enough"


def test_the_budget_still_closes_the_loop_for_a_visitor_who_will_not_answer():
    """
    Raising the requirement must not create a conversation nobody can leave. The
    budget is the guarantee, and it was raised in step so coverage stays reachable.
    """
    from apps.agents.services.stop_rule import question_budget

    assert question_budget(2) >= 4


def test_the_reveal_handoff_never_embeds_a_review_credential():
    from apps.conversations.views_thread import WHAT_HAPPENS_NEXT, _append_client_page_link

    out = _append_client_page_link("Here is your review.", "https://web.test/c/tok.sig")

    assert "https://web.test/c/tok.sig" not in out
    assert "View My Review" in out
    assert WHAT_HAPPENS_NEXT in out
    assert "decision-support artifact" in out


# ── generation completeness ─────────────────────────────────────────────────


def test_truncated_json_is_salvaged_as_clean_prose_not_raw_json():
    from apps.agents.services.concierge import ConciergeAgent

    raw = '{"reply": "First paragraph.\n\nSecond paragraph that ends mid-sentence'
    reply, suggest_nda = ConciergeAgent._parse_reply(raw, truncated=True)

    assert reply.startswith("First paragraph.")
    assert "Second paragraph" in reply
    assert not reply.lstrip().startswith("{")
    assert suggest_nda is False
    assert reply.endswith("…")


def test_valid_concierge_json_keeps_the_contract():
    from apps.agents.services.concierge import ConciergeAgent

    reply, suggest_nda = ConciergeAgent._parse_reply(
        '{"reply": "Complete answer.", "suggestNda": true}', truncated=False
    )

    assert reply == "Complete answer."
    assert suggest_nda is True

# ── current document doctrine / canonical taxonomy anchor ──────────────────

def test_brand_core_rejects_retired_split_and_anchors_current_taxonomy():
    from apps.ai_engine.services.system_prompt_builder import _BRAND_CORE

    assert "representation diagnosis — the adoption wedge" not in _BRAND_CORE
    assert "ALPHA Core (runtime/execution)" not in _BRAND_CORE
    assert "use only the supplied KNOWLEDGE CONTEXT, the canonical taxonomy below" in _BRAND_CORE
    assert "PRODUCTS — the complete currently sold product catalogue" in _BRAND_CORE
    assert "ASTOP" in _BRAND_CORE and "ALPHA Compute" in _BRAND_CORE and "ALPHA Core" in _BRAND_CORE
    assert "TECHNOLOGIES — these are NOT separately sold products" in _BRAND_CORE
    assert "Prefer current higher-authority sources" in _BRAND_CORE


def test_context_labels_current_canonical_sources_for_the_model():
    prompt = _prompt(
        "What are the two products?",
        chunks=[
            {
                "document_title": "itriX Product Canonical v3.5",
                "heading": "Canonical Product Taxonomy",
                "text": "itriX currently has three products: ASTOP, ALPHA Compute and ALPHA Core.",
                "canonical_priority": 100,
                "retrieval_backend": "pinecone",
            }
        ],
    )
    assert "CANONICAL/CURRENT" in prompt
    assert "itriX Product Canonical v3.5" in prompt
    assert "via pinecone" in prompt


def test_concierge_uses_the_full_visitor_knowledge_corpus_not_route_namespace():
    from apps.ai_engine.services.knowledge_retriever import VISITOR_KNOWLEDGE_NAMESPACES

    assert "company" in VISITOR_KNOWLEDGE_NAMESPACES
    assert "technology" in VISITOR_KNOWLEDGE_NAMESPACES
    assert "alpha-compute" in VISITOR_KNOWLEDGE_NAMESPACES
    assert "alpha-core" in VISITOR_KNOWLEDGE_NAMESPACES
    assert "general" not in VISITOR_KNOWLEDGE_NAMESPACES
