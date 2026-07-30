"""
``matchedText`` is the most sensitive field on Surface 2 (decision of 21 July).

It is the prohibited wording a model tried to emit. ADMIN and ASSESSMENT may see it;
SPECIALIST and VIEWER may not.

── THE FILTER MUST BE SERVER-SIDE, AND THAT IS WHAT THESE TESTS PIN ────────
A frontend that hid the field would still have RECEIVED it: the bytes would be in the
JSON, in the browser cache, and in anything that logged the response. A field that is only
hidden by the absence of a component is not access-controlled.

v7.1 Phase 1 fixed a live instance of exactly that: ``analytics/streaming/`` returned
``matchedText`` to any authenticated team member, VIEWER included. No component rendered
it, which is why nobody noticed.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def guard_hit():
    from apps.governance.models import StreamGuardHit

    return StreamGuardHit.objects.create(
        kind=StreamGuardHit.Kind.HALT,
        category="benchmark",
        pattern="performance_multiple",
        matched_text="10x faster than the baseline",
        agent_key="pitch",
        plane="anonymous",
        thread_id="thr-role-test",
    )


def _user(role: str):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        email=f"{role.lower()}@itrix.test",
        password="a-long-enough-password",
        role=role,
        is_active=True,
    )


@pytest.mark.parametrize("role,expected", [
    ("ADMIN", True),
    ("ASSESSMENT", True),
    ("SPECIALIST", False),
    ("VIEWER", False),
])
def test_permission_helper_matches_the_21_july_decision(role, expected):
    from apps.cockpit.permissions import may_see_matched_text

    assert may_see_matched_text(_user(role)) is expected


def test_helper_fails_closed_on_anything_unexpected():
    """
    A missing role, an anonymous user, an inactive user, a user object from a future auth
    backend. The cost of failing closed is an operator asking a colleague; the cost of
    failing open is the platform's prohibited wording in a role nobody reviewed for it.
    """
    from django.contrib.auth.models import AnonymousUser

    from apps.cockpit.permissions import may_see_matched_text

    assert may_see_matched_text(None) is False
    assert may_see_matched_text(AnonymousUser()) is False

    class Odd:
        is_authenticated = True
        is_active = True
        # no `role` attribute at all

    assert may_see_matched_text(Odd()) is False


def test_viewer_does_not_receive_the_key_at_all(guard_hit):
    """
    ABSENT, not empty. An empty string reads as "nothing was matched", which is false and
    would make a VIEWER think the halt was spurious.
    """
    from apps.cockpit.services import guard_hits

    rows = guard_hits.rows(may_see_matched_text=False)
    assert rows, "the fixture hit should be returned"
    for row in rows:
        assert "matchedText" not in row
        # The pattern IDENTIFIER is safe for every role: it names which rule fired without
        # reproducing the wording that fired it.
        assert row["pattern"] == "performance_multiple"


def test_admin_receives_it_with_the_notice_attached(guard_hit):
    """The label travels WITH the data, so a UI cannot render the text without it."""
    from apps.cockpit.services import guard_hits

    rows = guard_hits.rows(may_see_matched_text=True)
    assert rows[0]["matchedText"] == "10x faster than the baseline"
    assert rows[0]["matchedTextNotice"] == "Never sent to the visitor."


def test_the_service_default_is_the_restrictive_one(guard_hit):
    """
    An un-updated caller must fail closed. This is what makes the fix safe: the leak was a
    function that included the field unconditionally, so the default is now the guard.
    """
    from apps.analytics.services import stream_metrics
    from apps.cockpit.services import guard_hits

    assert "matchedText" not in guard_hits.rows()[0]
    assert "matchedText" not in stream_metrics.recent_hits()[0]


def test_the_streaming_aggregate_no_longer_leaks_to_viewer(guard_hit):
    """
    The live leak v7.1 Phase 1 closed. ``analytics/streaming/`` returned the field to any
    authenticated team member.
    """
    from rest_framework.test import APIClient

    for role, should_see in (("VIEWER", False), ("ADMIN", True)):
        client = APIClient()
        client.force_authenticate(user=_user(role))
        response = client.get("/api/v1/analytics/streaming/")
        assert response.status_code == 200, response.status_code
        body = response.json()
        assert body["matchedTextVisible"] is should_see
        for row in body["recent"]:
            assert ("matchedText" in row) is should_see
