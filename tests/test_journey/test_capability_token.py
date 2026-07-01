"""Capability token: round-trip, tamper rejection, expiry, and type checks."""

from __future__ import annotations

import time

import pytest

from apps.journey.services import capability_token as ct


def test_mint_and_verify_round_trip():
    token = ct.mint(sub="lead-1", typ=ct.TOKEN_CLIENT_PAGE, state="CLIENT_PAGE")
    payload = ct.verify(token, expected_typ=ct.TOKEN_CLIENT_PAGE)
    assert payload.sub == "lead-1"
    assert payload.typ == ct.TOKEN_CLIENT_PAGE
    assert payload.state == "CLIENT_PAGE"


def test_tampered_token_is_rejected():
    token = ct.mint(sub="lead-1", typ=ct.TOKEN_CLIENT_PAGE, state="CLIENT_PAGE")
    with pytest.raises(ct.CapabilityTokenError):
        ct.verify(token + "tampered")


def test_wrong_type_is_rejected():
    token = ct.mint(sub="lead-1", typ=ct.TOKEN_CLIENT_PAGE, state="CLIENT_PAGE")
    with pytest.raises(ct.CapabilityTokenError):
        ct.verify(token, expected_typ=ct.TOKEN_ACCOUNT_INVITE)


def test_expired_token_is_rejected():
    token = ct.mint(sub="lead-1", typ=ct.TOKEN_PORTAL, state="CLIENT", ttl_seconds=-1)
    with pytest.raises(ct.CapabilityTokenError):
        ct.verify(token)


def test_unknown_type_cannot_be_minted():
    with pytest.raises(ct.CapabilityTokenError):
        ct.mint(sub="x", typ="not_a_type", state="ARRIVED")


def test_single_use_flag_is_carried():
    token = ct.mint(sub="l", typ=ct.TOKEN_ACCOUNT_INVITE, state="INVITED", single_use=True)
    assert ct.verify(token).single_use is True
