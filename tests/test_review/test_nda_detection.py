"""NDA detector + immediate-response NDA reminder tests."""

from __future__ import annotations

import pytest

from apps.review.models import ReviewSession
from apps.review.services.immediate_response import build_immediate_response
from apps.review.services.nda_detector import detect_nda_signals

pytestmark = pytest.mark.django_db

SESSIONS_URL = "/api/v1/review/sessions/"


# ── Pure detector tests ──────────────────────────────────────────────────────
def test_detects_confidential_keyword():
    res = detect_nda_signals("This involves our confidential chip architecture.")
    assert res.nda_recommended is True
    assert "confidential" in res.matched_signals


def test_detects_proprietary_and_source_code():
    res = detect_nda_signals("We can share our source code and proprietary kernels.")
    assert res.nda_recommended is True
    assert any(s in res.matched_signals for s in ("our source code", "proprietary"))


def test_clean_prompt_does_not_trigger():
    res = detect_nda_signals("Our simulation is slow and memory-bound.")
    assert res.nda_recommended is False
    assert res.matched_signals == []


def test_empty_prompt_safe():
    res = detect_nda_signals("")
    assert res.nda_recommended is False


def test_no_false_positive_on_substring():
    # "confidence" should not match "confidential"
    res = detect_nda_signals("We have high confidence in our numbers.")
    assert res.nda_recommended is False


# ── Immediate response surfaces the NDA reminder ─────────────────────────────
def test_immediate_response_includes_nda_reminder_when_triggered():
    ir = build_immediate_response("This is confidential and under NDA.", ["cost"])
    assert ir.nda_reminder is not None
    assert "NDA" in ir.nda_reminder


def test_immediate_response_no_reminder_for_clean_prompt():
    ir = build_immediate_response("Our solver is slow.", ["speed"])
    assert ir.nda_reminder is None
    assert ir.reflected_pressures == ["speed"]


# ── End-to-end: prompt endpoint sets the flag + returns reminder ─────────────
def test_prompt_endpoint_flags_nda(api_client):
    sid = api_client.post(SESSIONS_URL, {}, format="json").json()["id"]
    url = f"{SESSIONS_URL}{sid}/prompt/"
    resp = api_client.post(
        url,
        {"prompt": "We want to share our proprietary trade secret implementation."},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json()["nda_recommended"] is True

    obj = ReviewSession.objects.get(pk=sid)
    assert obj.nda_recommended is True
    assert len(obj.nda_signals) >= 1
