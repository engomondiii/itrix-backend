"""
Message length (Backend v6.0 §2.3, R28).

THERE IS NO USER-FACING CHARACTER LIMIT. The cap is a server safety limit that returns a
specific, recoverable message — never a silent truncation of the visitor's problem.
"""

from __future__ import annotations

import pytest

from apps.conversations.models import MessageTooLong, max_message_chars, validate_message_length

pytestmark = pytest.mark.django_db


def test_a_long_message_is_accepted():
    """20,000 characters is a real thing a person pastes. It must simply work."""
    body = "x" * 20_000
    assert validate_message_length(body) == body


def test_the_cap_is_generous():
    assert max_message_chars() >= 100_000


def test_over_the_cap_raises_with_a_recoverable_message():
    with pytest.raises(MessageTooLong) as exc:
        validate_message_length("x" * (max_message_chars() + 1))
    message = str(exc.value)
    # The visitor must be told what to do, and reassured nothing was lost.
    assert "longer than we can accept" in message
    assert "nothing you have already written is lost" in message


def test_nothing_is_silently_truncated():
    """
    The failure mode this guards against: returning a shortened body and pretending it
    was the whole message.
    """
    body = "x" * (max_message_chars() + 1)
    with pytest.raises(MessageTooLong):
        validate_message_length(body)


def test_empty_body_is_allowed():
    assert validate_message_length("") == ""
