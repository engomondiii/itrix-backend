"""
Streaming-governance analytics (Backend v6.0 §Phase 3, §6.4).

    A rising guard-hit rate is treated as RETRIEVAL OR PROMPT DRIFT, NOT AS NOISE.

That interpretation rule is why the module reports a TREND, not just a total.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.analytics.services import stream_metrics
from apps.governance.models import StreamGuardHit

pytestmark = pytest.mark.django_db


def _hit(**kwargs):
    defaults = {
        "kind": StreamGuardHit.Kind.HALT, "category": "benchmark",
        "pattern": r"\d+% faster", "matched_text": "30% faster",
        "agent_key": "concierge", "plane": "public",
    }
    defaults.update(kwargs)
    return StreamGuardHit.objects.create(**defaults)


def test_totals_separate_the_three_kinds():
    _hit()
    _hit(kind=StreamGuardHit.Kind.ENVELOPE_DOWNGRADE)
    _hit(kind=StreamGuardHit.Kind.SETTLE_REPLACEMENT)
    totals = stream_metrics.totals()
    assert totals["halts"] == 1
    assert totals["envelopeDowngrades"] == 1
    assert totals["settleReplacements"] == 1


def test_by_category_is_the_actionable_breakdown():
    """
    A spike in ``benchmark`` means retrieval is surfacing unapproved figures; a spike in
    ``inferred_identity`` means the prompt has drifted toward profiling. The total alone
    cannot distinguish them.
    """
    _hit(category="benchmark")
    _hit(category="inferred_identity")
    _hit(category="inferred_identity")
    by_category = stream_metrics.by_category()
    assert by_category["inferred_identity"] == 2
    assert by_category["benchmark"] == 1


def test_by_plane_surfaces_the_anonymous_plane():
    """The newest surface, and the one where a halt has the widest blast radius."""
    _hit(plane="public")
    _hit(plane="client")
    assert stream_metrics.by_plane()["public"] == 1


def test_by_agent_attributes_the_hit():
    _hit(agent_key="concierge")
    _hit(agent_key="pitch")
    assert set(stream_metrics.by_agent()) >= {"concierge", "pitch"}


def test_the_drift_signal_compares_recent_against_baseline():
    """The rule in code: is the rate RISING, not merely non-zero."""
    old = timezone.now() - timezone.timedelta(days=20)
    for _ in range(2):
        hit = _hit()
        StreamGuardHit.objects.filter(id=hit.id).update(created_at=old)
    for _ in range(10):
        _hit()

    drift = stream_metrics.drift_signal()
    assert drift["recent"] == 10
    assert drift["baseline"] == 2
    assert drift["rising"] is True


def test_a_flat_rate_is_not_flagged_as_drift():
    """A jump from 1 to 3 must not read as a crisis."""
    drift = stream_metrics.drift_signal()
    assert drift["rising"] is False


def test_the_drift_report_states_the_interpretation():
    """
    The number is useless without the rule. An operator seeing "halts: 40" needs to know
    that means drift, not that the guard is working well.
    """
    assert "drift, not noise" in stream_metrics.drift_signal()["interpretation"]


def test_recent_hits_carry_the_matched_text_for_a_permitted_operator():
    """
    ``matchedText`` is the prohibited wording itself. It exists so an operator can see what
    the model tried to say — and it must never leave the team plane.

    ── v7.1 PHASE 1 NARROWED THIS FROM "the team plane" TO "two roles" ──────
    This test used to call ``recent_hits()`` with no argument and assert the field was
    present. It was, for everyone — and ``analytics/streaming/`` calls this function for any
    authenticated team member, so a VIEWER was receiving the platform's own prohibited
    wording in plain text, against the decision of 21 July that limits it to ADMIN and
    ASSESSMENT.

    Nothing rendered it, which is precisely why it went unnoticed: the bytes were in the
    JSON, in the browser cache, and in anything that logged the response. A field hidden
    only by the absence of a component is not access-controlled.

    So the assertion now names the permission it depends on.
    """
    _hit(matched_text="30% faster")
    recent = stream_metrics.recent_hits(may_see_matched_text=True)
    assert recent and recent[0]["matchedText"] == "30% faster"
    # The label travels WITH the data, so a UI cannot render the text without it.
    assert recent[0]["matchedTextNotice"] == "Never sent to the visitor."


def test_recent_hits_default_to_withholding_the_matched_text():
    """
    THE DEFAULT IS THE GUARD.

    The leak was a function that included the field unconditionally, so the fix has to be
    safe for a caller nobody remembered to update. The key is ABSENT rather than empty — an
    empty string reads as "nothing was matched", which is false and would make an operator
    think the halt was spurious.

    The pattern IDENTIFIER is still returned to every role: it names which rule fired
    without reproducing the wording that fired it.
    """
    _hit(matched_text="30% faster")
    recent = stream_metrics.recent_hits()
    assert recent
    assert "matchedText" not in recent[0]
    assert "matchedTextNotice" not in recent[0]
    assert recent[0]["pattern"] == r"\d+% faster"


def test_the_endpoint_is_team_gated():
    from apps.analytics.views_v6 import StreamingAnalyticsView

    classes = [c.__name__ for c in StreamingAnalyticsView.permission_classes]
    assert "IsDashboardUser" in classes
    assert "AllowAny" not in classes
