"""
The attachment policy table (Backend v6.0 §4.2, R25).

The rule that is easiest to break by accident: ANY type, ANY number. The limits are
SAFETY and ABUSE ceilings, not product limits, and each carries a recoverable message.
"""

from __future__ import annotations

import pytest

from apps.attachments import policy


def test_any_file_type_is_accepted():
    """R25: files of ANY format. A type check that rejects is a product limit."""
    for name, mime in [
        ("model.safetensors", "application/octet-stream"),
        ("weird.xyz", "application/x-unknown"),
        ("archive.7z", "application/x-7z-compressed"),
        ("notes.txt", "text/plain"),
    ]:
        assert policy.check_type(mime, name).allowed


def test_there_is_no_product_level_file_count_limit():
    snapshot = policy.snapshot()
    assert snapshot["file_count_per_turn"] == "no product limit"
    assert snapshot["file_type"] == "any"


def test_oversized_file_is_refused_with_a_recoverable_message():
    decision = policy.check_file_size(policy.max_attachment_bytes() + 1)
    assert not decision.allowed
    # It must tell them what they CAN still do.
    assert "send the message without it" in decision.message


def test_a_normal_file_passes():
    assert policy.check_file_size(5 * 1024 * 1024).allowed


def test_turn_total_ceiling_names_the_recovery():
    decision = policy.check_turn_total(policy.max_attachment_bytes_per_turn() + 1)
    assert not decision.allowed
    assert "follow-up" in decision.message


def test_session_ceiling_is_non_punitive():
    """
    A person hitting an abuse ceiling accidentally must not be addressed as an attacker.
    """
    decision = policy.check_session_count(policy.max_attachments_per_session())
    assert not decision.allowed
    for accusatory in ("abuse", "blocked", "violation", "denied", "suspicious"):
        assert accusatory not in decision.message.lower()


def test_pre_nda_retention_is_shorter_than_post_nda():
    """§4.7: pre-NDA material carries a SHORTER window."""
    assert policy.retention_days_for(pre_nda=True) < policy.retention_days_for(pre_nda=False)


def test_archive_bomb_limits_are_set():
    assert policy.MAX_ARCHIVE_RATIO > 0
    assert policy.MAX_ARCHIVE_DEPTH > 0
    assert policy.MAX_ARCHIVE_ENTRIES > 0
