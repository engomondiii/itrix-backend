"""
Private feedback (Playbook §12I, Architecture §7.4).

    This is private. It goes to your customer-success owner and NOWHERE ELSE.

Three rules:
  1. A pulse score is NEVER rendered back to the customer as a judgement about them.
  2. It is never used in copy addressed to them.
  3. It is never shown outside the success team.

The endpoint is WRITE-ONLY because that is the only version of "private" which survives
refactoring: if a customer could read their score back, it would exist in a client-plane
payload, and some future surface would render it.
"""

from __future__ import annotations

import pytest

from apps.customer_success.services import feedback_pulse

pytestmark = pytest.mark.django_db


def test_a_pulse_is_recorded(paying_client):
    pulse = feedback_pulse.submit(paying_client, score=2, comment="Slower than we hoped")
    assert pulse.score == 2
    assert pulse.comment == "Slower than we hoped"


def test_there_is_no_client_plane_read_function():
    """
    STRUCTURAL. No ``get_my_pulses``. The only reader is named for the success team, and
    the name is deliberately awkward so a mistaken import reads wrong at the call site.
    """
    assert not hasattr(feedback_pulse, "get_my_pulses")
    assert not hasattr(feedback_pulse, "for_client")
    assert hasattr(feedback_pulse, "recent_for_success_team")


def test_the_submit_serializer_is_not_a_model_serializer():
    """
    A ModelSerializer would return the created instance's fields — INCLUDING score —
    straight back in the response body.
    """
    from rest_framework import serializers

    from apps.customer_success.serializers import FeedbackPulseSubmitSerializer

    assert not issubclass(FeedbackPulseSubmitSerializer, serializers.ModelSerializer)


def test_the_feedback_route_has_no_get():
    from apps.customer_success.views import FeedbackView

    assert hasattr(FeedbackView, "post")
    assert not hasattr(FeedbackView, "get")


def test_the_response_carries_no_score(paying_client):
    """The acknowledgement must not echo anything correlatable."""
    from rest_framework.test import APIRequestFactory

    from apps.customer_success.views import FeedbackView

    request = APIRequestFactory().post("/", {"score": 1, "comment": "unhappy"}, format="json")
    request.user = paying_client
    response = FeedbackView.as_view()(request)
    body = str(response.data)
    assert "score" not in body.lower()
    assert "1" not in body.replace("12I", "")


def test_no_customer_facing_serializer_exposes_a_score():
    """Rule 1, asserted across every client-plane serializer in the module."""
    import inspect

    from rest_framework import serializers

    from apps.customer_success import serializers as module

    for name, obj in inspect.getmembers(module, inspect.isclass):
        if not issubclass(obj, serializers.Serializer) or name.startswith("Team"):
            continue
        fields = getattr(getattr(obj, "Meta", None), "fields", []) or []
        assert "score" not in fields, f"{name} exposes a pulse score"


def test_the_team_serializer_does_carry_the_score():
    """The success team is the ONE place it is legitimately visible."""
    from apps.customer_success.serializers import TeamFeedbackPulseSerializer

    assert "score" in TeamFeedbackPulseSerializer.Meta.fields


def test_customer_health_is_absent_from_every_client_serializer():
    """``customer_health`` is on the §10.5 internal-only list."""
    import inspect

    from rest_framework import serializers

    from apps.customer_success import serializers as module

    for name, obj in inspect.getmembers(module, inspect.isclass):
        if not issubclass(obj, serializers.Serializer) or name.startswith("Team"):
            continue
        fields = getattr(getattr(obj, "Meta", None), "fields", []) or []
        assert "customer_health" not in fields
        assert "customerHealth" not in fields


def test_a_negative_pulse_is_a_trust_signal_for_the_nba_rule(paying_client):
    feedback_pulse.submit(paying_client, score=1, comment="Not going well")
    assert feedback_pulse.has_negative_signal(paying_client) is True


def test_a_positive_pulse_is_not_a_negative_signal(paying_client):
    feedback_pulse.submit(paying_client, score=5, comment="Great")
    assert feedback_pulse.has_negative_signal(paying_client) is False
