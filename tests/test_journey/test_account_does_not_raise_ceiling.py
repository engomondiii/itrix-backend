"""
AN ACCOUNT IS NOT A LEVER (Architecture v2.9 R59).

This is the test that makes open registration safe to reason about. The whole objection in
v2.8 §00.2 was "a Client with no Lead, no NDA and no conversation has no position — so what
may they see?" The answer is in one expression:

    effective_ceiling = min(plane_cap, STATE_CEILING[journey_number(state)])

Nothing in it mentions an account. This asserts that AT EVERY STATE, so a future edit that
lets account existence enter the calculation fails here rather than in production.
"""

from __future__ import annotations

import pytest

from apps.journey.constants import STATE_KEYS
from apps.journey.services.shell import (
    IDENTITY_ANONYMOUS,
    IDENTITY_IDENTIFIED,
    disclosure_ceiling_for,
)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("state", STATE_KEYS)
def test_a_registered_subject_reaches_what_an_anonymous_one_reaches(state):
    """
    Without an NDA, the two are equal at every state. Signing up changes where your work is
    KEPT, not what we are able to show you (Disclosure Policy §2).
    """
    anonymous = disclosure_ceiling_for(state, IDENTITY_ANONYMOUS, nda_signed=False)
    registered = disclosure_ceiling_for(state, IDENTITY_IDENTIFIED, nda_signed=False)
    assert anonymous == registered, (
        f"state {state}: an account changed the ceiling from {anonymous} to {registered}. "
        "That is R59, and it is the reason open registration is safe."
    )


def test_a_silent_registered_account_is_capped_at_public():
    """State 1 is `public`. A person who registers on arrival and says nothing sees exactly
    what a stranger sees."""
    assert disclosure_ceiling_for("ARRIVED", IDENTITY_IDENTIFIED, nda_signed=False) == "public"


def test_an_nda_is_what_moves_the_ceiling_not_an_account():
    """The thing that actually raises reach is a contractual position, and it has to be
    signed — which itself requires a confirmed address (R66)."""
    without = disclosure_ceiling_for("NDA_REVIEW", IDENTITY_IDENTIFIED, nda_signed=False)
    with_nda = disclosure_ceiling_for("NDA_REVIEW", IDENTITY_IDENTIFIED, nda_signed=True)
    assert without != with_nda
