"""
The trailing-punctuation failure that told real visitors their link had expired.

A minted token is ``<payload>.<signature>`` — it contains a period. The reveal
message wrote the URL inside a sentence, so the sentence's full stop landed flush
against the signature. Anyone selecting the link by hand carried that full stop
into the request, ``verify`` split on the first period, base64 got the punctuation,
the signature failed, and the visitor was told the review link was unavailable —
with two weeks of validity left on it.
"""

from __future__ import annotations

import pytest

from apps.journey.services import capability_token as ct


def _token() -> str:
    return ct.mint(
        sub="11111111-1111-1111-1111-111111111111",
        typ=ct.TOKEN_CLIENT_PAGE,
        state="CLIENT_PAGE",
        ttl_seconds=14 * 24 * 3600,
    )


def test_a_clean_token_still_verifies():
    payload = ct.verify(_token(), expected_typ=ct.TOKEN_CLIENT_PAGE)
    assert payload.sub == "11111111-1111-1111-1111-111111111111"


@pytest.mark.parametrize(
    "trailing",
    ['.', ',', ';', ':', '!', '?', ')', ']', '}', "'", '"', '\u201d', '\u2019', ' ', '\u00a0', '.)', '".'],
)
def test_punctuation_carried_in_from_prose_no_longer_breaks_the_link(trailing):
    """This is the production case: a full stop, or a quote and a full stop."""
    payload = ct.verify(_token() + trailing, expected_typ=ct.TOKEN_CLIENT_PAGE)
    assert payload.typ == ct.TOKEN_CLIENT_PAGE


def test_leading_and_trailing_whitespace_is_tolerated():
    """Copy-paste out of a chat transcript picks up whitespace at both ends."""
    assert ct.verify(f"  {_token()}\n", expected_typ=ct.TOKEN_CLIENT_PAGE).sub


def test_tidying_cannot_rescue_a_token_that_should_fail():
    """
    The important half of the guarantee. Only trailing whitespace and sentence
    punctuation come off — none of which can appear in a valid base64url
    signature — so nothing that would have failed verification now passes.
    """
    good = _token()
    payload_b64, sig_b64 = good.split(".", 1)

    with pytest.raises(ct.CapabilityTokenError):
        ct.verify(f"{payload_b64}.{sig_b64[:-4]}XXXX", expected_typ=ct.TOKEN_CLIENT_PAGE)

    with pytest.raises(ct.CapabilityTokenError):
        # A truncated signature is what a selection that stopped at the FIRST
        # period produces. It must still be refused.
        ct.verify(payload_b64, expected_typ=ct.TOKEN_CLIENT_PAGE)

    with pytest.raises(ct.CapabilityTokenError):
        ct.verify("", expected_typ=ct.TOKEN_CLIENT_PAGE)


def test_the_wrong_token_type_is_still_refused_after_tidying():
    with pytest.raises(ct.CapabilityTokenError):
        ct.verify(_token() + ".", expected_typ="something_else")
