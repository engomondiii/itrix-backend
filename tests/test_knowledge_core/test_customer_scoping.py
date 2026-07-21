"""
The sixth tier: customer_contract, SCOPED PER CUSTOMER (Backend v6.0 §8.1, §8.3).

    customer_contract (scoped per customer, NEVER CROSS-SERVED)

Reaching the tier is not sufficient. One customer's contract material must never answer
another customer's question, so scope is a SECOND gate applied after the tier check.
"""

from __future__ import annotations

import pytest

from apps.ai_engine.services.disclosure_filter import (
    CONTEXT_ALLOWED,
    allowed_levels,
    filter_chunks,
    is_allowed,
)


def _chunk(level, scope="", text="x"):
    return {"disclosure_level": level, "customer_scope": scope, "text": text}


def test_the_sixth_tier_exists():
    assert "customer_contract" in CONTEXT_ALLOWED
    assert "customer_contract" in allowed_levels("customer_contract")


def test_a_public_caller_cannot_reach_the_tier():
    assert is_allowed("customer_contract", context="public") is False
    assert is_allowed("customer_contract", context="controlled") is False


def test_an_nda_caller_cannot_reach_the_tier():
    """A signed NDA is not a contract. The tiers are earned separately."""
    assert is_allowed("customer_contract", context="nda") is False


def test_a_contracted_customer_reaches_their_own_material():
    kept = filter_chunks([_chunk("customer_contract", "cust-a")],
                         context="customer_contract", customer_scope="cust-a")
    assert len(kept) == 1


def test_a_contracted_customer_cannot_reach_another_customers_material():
    """THE CROSS-SERVING TEST. This is the whole point of the second gate."""
    kept = filter_chunks([_chunk("customer_contract", "cust-b")],
                         context="customer_contract", customer_scope="cust-a")
    assert kept == []


def test_an_unscoped_contract_chunk_is_never_served():
    """
    Default closed. A contract chunk with no scope cannot be matched by anybody, which
    is safer than treating "no scope" as "everyone".
    """
    kept = filter_chunks([_chunk("customer_contract", "")],
                         context="customer_contract", customer_scope="cust-a")
    assert kept == []


def test_a_caller_with_no_scope_matches_nothing():
    kept = filter_chunks([_chunk("customer_contract", "cust-a")],
                         context="customer_contract", customer_scope="")
    assert kept == []


def test_lower_tiers_are_unaffected_by_scope():
    """Scoping applies to the sixth tier only — public material stays public."""
    kept = filter_chunks(
        [_chunk("public"), _chunk("controlled_public"), _chunk("nda_only")],
        context="customer_contract", customer_scope="cust-a",
    )
    assert len(kept) == 3


def test_the_team_plane_can_review_contract_material():
    """Internal review must be able to see the material it is reviewing."""
    kept = filter_chunks([_chunk("customer_contract", "cust-b")],
                         context="internal", customer_scope="")
    assert len(kept) == 1


def test_prohibited_is_never_served_at_any_tier():
    for context in ("public", "controlled", "nda", "customer_contract", "internal"):
        assert filter_chunks([_chunk("prohibited")], context=context) == []


def test_internal_only_is_not_reachable_from_the_customer_tier():
    kept = filter_chunks([_chunk("internal_only")],
                         context="customer_contract", customer_scope="cust-a")
    assert kept == []
