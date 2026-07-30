"""
AGGREGATES under analytics/, ROW-LEVEL RESOURCES under cockpit/ (Backend v7.1 §Phase 1).

── WHY THIS IS A TEST AND NOT A CONVENTION ─────────────────────────────────
v6.0 mounted four ANALYTICS views at ``cockpit/`` as well as at ``analytics/``, so
``cockpit/threads/`` returned thread METRICS while the dashboard was asking it for a
thread LIST. The dashboard's 501 guards were read as "the backend has not built this yet"
when in fact the name was occupied by an aggregate.

A convention could not have caught that, because both endpoints worked. Only a test that
asserts WHICH SHAPE each name returns can.
"""

from __future__ import annotations

import pytest
from django.urls import resolve, reverse

pytestmark = pytest.mark.django_db


AGGREGATE_PATHS = (
    "/api/v1/analytics/customers/",
    "/api/v1/analytics/conversations/",
    "/api/v1/analytics/attachments/",
    "/api/v1/analytics/streaming/",
)

RESOURCE_PATHS = (
    "/api/v1/cockpit/threads/",
    "/api/v1/cockpit/customers/",
    "/api/v1/cockpit/streaming/guard-hits/",
    # v7.1 Phase 2
    "/api/v1/cockpit/support/queue/",
    "/api/v1/cockpit/attachments/",
)


def test_the_four_freed_cockpit_names_no_longer_resolve_to_aggregates():
    """
    ``cockpit/threads/`` and ``cockpit/customers/`` now resolve to the ROW-LEVEL views.

    The check is on the resolved view class, not on the response body: an aggregate that
    happened to return an empty dict would pass a shape check and fail this one.
    """
    from apps.cockpit.views import CockpitCustomerBoardView, CockpitThreadBoardView

    assert resolve("/api/v1/cockpit/threads/").func.view_class is CockpitThreadBoardView
    assert resolve("/api/v1/cockpit/customers/").func.view_class is CockpitCustomerBoardView


def test_cockpit_attachments_is_now_the_review_queue_not_an_aggregate():
    """
    ── UPDATED BY v7.1 PHASE 2 ─────────────────────────────────────────────
    The Phase 1 version of this test asserted ``cockpit/attachments/`` returned 404, because
    Phase 1 freed the name and left it empty. Phase 2 is what it was freed FOR: the
    attachment review queue now owns it.

    So the assertion changes from "nothing answers here" to "the ROW-LEVEL view answers
    here" — which is the property that actually matters. What must never be true again is
    that this name returns attachment METRICS.
    """
    from apps.analytics.views_v6 import AttachmentAnalyticsView
    from apps.cockpit.views import CockpitAttachmentQueueView

    resolved = resolve("/api/v1/cockpit/attachments/").func.view_class
    assert resolved is CockpitAttachmentQueueView
    assert resolved is not AttachmentAnalyticsView

    # And the aggregate is still where it belongs.
    assert resolve("/api/v1/analytics/attachments/").func.view_class is AttachmentAnalyticsView


def test_cockpit_streaming_bare_is_still_not_a_route():
    """
    Only ``streaming/guard-hits/`` is mounted. The bare name stays unassigned, because a
    name that still answered with the old aggregate meaning is the hardest kind of stale
    contract to notice.
    """
    from django.urls.exceptions import Resolver404

    with pytest.raises(Resolver404):
        resolve("/api/v1/cockpit/streaming/")


def test_the_aggregates_still_live_under_analytics():
    """
    They were ALREADY mounted here in v6.0. Phase 1 removes the second door, it does not
    move the aggregates — so a dashboard proxy re-pointed at analytics/* keeps working.
    """
    from apps.analytics.views_v6 import (
        AttachmentAnalyticsView,
        ConversationAnalyticsView,
        CustomerHealthAnalyticsView,
        StreamingAnalyticsView,
    )

    expected = {
        "/api/v1/analytics/customers/": CustomerHealthAnalyticsView,
        "/api/v1/analytics/conversations/": ConversationAnalyticsView,
        "/api/v1/analytics/attachments/": AttachmentAnalyticsView,
        "/api/v1/analytics/streaming/": StreamingAnalyticsView,
    }
    for path, view in expected.items():
        assert resolve(path).func.view_class is view, path


def test_every_cockpit_resource_requires_a_team_member():
    """
    Every route here reads §10.5 internal-only material — governance status, claim levels,
    cited chunk ids, health classes, halts. None of it is reachable on the anonymous or
    client plane at any state.
    """
    from rest_framework.test import APIClient

    client = APIClient()
    for path in RESOURCE_PATHS:
        response = client.get(path)
        assert response.status_code in (401, 403), f"{path} answered {response.status_code}"
