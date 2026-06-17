"""Disclosure-filter tests — the five-tier guard."""

from __future__ import annotations

from apps.ai_engine.services.disclosure_filter import (
    filter_chunks,
    filter_proofs,
    is_allowed,
)


def _chunk(level):
    return {"text": "x", "disclosure_level": level}


def test_public_context_only_public():
    chunks = [_chunk("public"), _chunk("nda_only"), _chunk("internal_only"), _chunk("prohibited")]
    kept = filter_chunks(chunks, context="public")
    assert [c["disclosure_level"] for c in kept] == ["public"]


def test_nda_context_allows_public_and_nda():
    chunks = [_chunk("public"), _chunk("controlled_public"), _chunk("nda_only"), _chunk("internal_only")]
    kept = filter_chunks(chunks, context="nda")
    levels = {c["disclosure_level"] for c in kept}
    assert levels == {"public", "controlled_public", "nda_only"}


def test_prohibited_never_allowed():
    assert is_allowed("prohibited", context="internal") is False
    kept = filter_chunks([_chunk("prohibited")], context="internal")
    assert kept == []


def test_internal_only_excluded_in_public():
    assert is_allowed("internal_only", context="public") is False


def test_filter_proofs_public():
    proofs = [
        {"title": "a", "disclosure": "public"},
        {"title": "b", "disclosure": "nda_only"},
        {"title": "c", "disclosure": "internal_only"},
    ]
    kept = filter_proofs(proofs, context="public")
    assert {p["disclosure"] for p in kept} == {"public"}


def test_metadata_nested_disclosure_level():
    chunk = {"text": "x", "metadata": {"disclosure_level": "internal_only"}}
    assert filter_chunks([chunk], context="public") == []
