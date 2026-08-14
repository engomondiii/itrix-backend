from apps.agents.services.governance import govern_text, is_non_blocking_conversation_context


def test_public_concierge_contexts_are_non_blocking():
    for context in ("anonymous_review", "review", "client_page", "portal"):
        assert is_non_blocking_conversation_context(context, claim_level=1)


def test_quantified_overclaim_is_softened_not_held_in_public_conversation():
    decision = govern_text(
        "ALPHA Compute is 10x faster on this workload.",
        claim_level=1,
        context="anonymous_review",
    )
    assert decision["status"] == "auto_approved"
    assert "10x faster" not in decision["text"].lower()
    assert "subject to validation" in decision["text"].lower()


def test_higher_risk_non_conversation_governance_is_unchanged():
    decision = govern_text(
        "ALPHA Compute is 10x faster on this workload.",
        claim_level=4,
        context="team",
    )
    assert decision["status"] == "pending"
