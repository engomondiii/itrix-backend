"""
THE SUPPORT QUEUE (Backend v7.1 Phase 2, §18.7).

── WHY THIS ENDPOINT IS LOAD-BEARING RATHER THAN CONVENIENT ────────────────

The backend suppresses every commercial action while a blocking support request is open.
An operator who cannot SEE those requests experiences that as the system being obstructive
— "why won't it let me send the expansion note?" — and the predictable response is to hunt
for the override.

So the queue exists to make the rule legible: blocking first, and every row says whether it
is currently suppressing expansion for its customer. The operator meets the reason before
the consequence.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from tests.factories.client_factory import ClientFactory

pytestmark = pytest.mark.django_db


def _team_client(role: str = "ASSESSMENT"):
    from django.contrib.auth import get_user_model
    from rest_framework.test import APIClient

    User = get_user_model()
    user = User.objects.create_user(
        email=f"{role.lower()}-support@itrix.test",
        password="a-long-enough-password",
        role=role,
        is_active=True,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _request(client=None, **kwargs):
    from apps.customer_success.models import SupportRequest

    defaults = {
        "client": client or ClientFactory(),
        "subject": "Inference latency spike",
        "body": "Since Tuesday every batch takes twice as long.",
        "status": SupportRequest.Status.OPEN,
        "urgency": SupportRequest.Urgency.NORMAL,
        "blocking": False,
    }
    defaults.update(kwargs)
    return SupportRequest.objects.create(**defaults)


def test_blocking_outranks_urgency():
    """
    A NORMAL-urgency blocking request beats a CRITICAL non-blocking one.

    That ordering is deliberate and is the whole point of the sort key. Urgency is somebody's
    estimate; blocking is a fact about whether the customer can proceed at all.
    """
    from apps.customer_success.models import SupportRequest

    _request(subject="critical but not blocking", urgency=SupportRequest.Urgency.CRITICAL, blocking=False)
    _request(subject="normal but blocking", urgency=SupportRequest.Urgency.NORMAL, blocking=True)

    rows = _team_client().get("/api/v1/cockpit/support/queue/").json()["results"]
    assert rows[0]["subject"] == "normal but blocking"


def test_every_row_says_whether_it_suppresses_expansion():
    """The operator meets the reason before the consequence."""
    _request(subject="blocking", blocking=True)
    _request(subject="not blocking", blocking=False)

    rows = {r["subject"]: r for r in _team_client().get("/api/v1/cockpit/support/queue/").json()["results"]}
    assert rows["blocking"]["suppressesExpansion"] is True
    assert rows["not blocking"]["suppressesExpansion"] is False


def test_a_resolved_blocking_request_no_longer_suppresses():
    """Suppression follows `blocking AND open`, not `blocking` alone."""
    from apps.customer_success.models import SupportRequest

    req = _request(blocking=True, status=SupportRequest.Status.RESOLVED, resolved_at=timezone.now())
    rows = _team_client().get("/api/v1/cockpit/support/queue/?includeResolved=true").json()["results"]
    row = next(r for r in rows if r["requestId"] == str(req.id))
    assert row["blocking"] is True
    assert row["suppressesExpansion"] is False


def test_the_queue_excludes_resolved_by_default():
    from apps.customer_success.models import SupportRequest

    _request(subject="open one")
    _request(subject="done one", status=SupportRequest.Status.RESOLVED, resolved_at=timezone.now())

    subjects = [r["subject"] for r in _team_client().get("/api/v1/cockpit/support/queue/").json()["results"]]
    assert "open one" in subjects
    assert "done one" not in subjects


def test_customer_confirmed_resolved_keeps_its_three_states():
    """
    None means "not asked yet". False means the customer said it did NOT fix their problem —
    the most important value on the row, and the one a naive boolean would have erased.
    """
    from apps.customer_success.models import SupportRequest

    unasked = _request(subject="unasked", status=SupportRequest.Status.RESOLVED)
    denied = _request(
        subject="denied", status=SupportRequest.Status.RESOLVED, customer_confirmed_resolved=False
    )

    rows = {
        r["requestId"]: r
        for r in _team_client().get("/api/v1/cockpit/support/queue/?includeResolved=true").json()["results"]
    }
    assert rows[str(unasked.id)]["customerConfirmedResolved"] is None
    assert rows[str(denied.id)]["customerConfirmedResolved"] is False


def test_the_summary_counts_what_the_operator_needs():
    from apps.customer_success.models import SupportRequest

    _request(blocking=True)
    _request(blocking=False)
    _request(
        status=SupportRequest.Status.RESOLVED,
        customer_confirmed_resolved=False,
        resolved_at=timezone.now(),
    )

    summary = _team_client().get("/api/v1/cockpit/support/queue/").json()["summary"]
    assert summary["open"] == 2
    assert summary["blockingOpen"] == 1
    # Resolved but the customer disagreed. Not a queue item by status, very much one in practice.
    assert summary["resolvedButNotConfirmed"] == 1


def test_sla_breach_is_reported_as_a_fact_not_a_flag_alone():
    _request(subject="overdue", sla_due_at=timezone.now() - timezone.timedelta(hours=3))
    row = next(
        r for r in _team_client().get("/api/v1/cockpit/support/queue/").json()["results"]
        if r["subject"] == "overdue"
    )
    assert row["slaBreaching"] is True
    # How overdue, so the operator can triage between two breaching rows.
    assert row["overdueSeconds"] > 0


def test_no_commercial_signal_appears_on_a_support_row():
    """
    A support queue carrying a licence-out probability would invite an operator to open a
    customer's problem and leave with a sales action — the precise inversion the
    customer-first rule exists to prevent.
    """
    _request()
    row = _team_client().get("/api/v1/cockpit/support/queue/").json()["results"][0]
    for forbidden in ("licenseOutProbability", "leadScore", "tier", "personaId", "expansionCandidate"):
        assert forbidden not in row


def test_the_detail_returns_the_customers_own_words():
    """Not summarised, not truncated, not re-worded — a summary is where the detail that mattered gets lost."""
    req = _request(body="Since Tuesday every batch takes twice as long, and the retry loop never exits.")
    body = _team_client().get(f"/api/v1/cockpit/support/queue/{req.id}/").json()
    assert body["body"] == "Since Tuesday every batch takes twice as long, and the retry loop never exits."


def test_the_queue_is_team_gated():
    from rest_framework.test import APIClient

    response = APIClient().get("/api/v1/cockpit/support/queue/")
    assert response.status_code in (401, 403)


def test_an_unknown_request_is_404():
    import uuid

    assert _team_client().get(f"/api/v1/cockpit/support/queue/{uuid.uuid4()}/").status_code == 404
