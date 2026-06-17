"""Email sender + builder tests (delivery stubbed when ENABLE_EMAIL_DELIVERY=False)."""

from __future__ import annotations

import pytest
from django.test import override_settings

from apps.emails.models import EmailLog
from apps.emails.services.email_sender import send_email
from apps.emails.services.template_renderer import extract_variables, render
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def test_template_renderer_substitutes_variables():
    out = render("Hi {{name}}, route {{route}}.", {"name": "Dana", "route": "ALPHA Core"})
    assert out == "Hi Dana, route ALPHA Core."


def test_template_renderer_unknown_var_is_empty():
    assert render("Hello {{missing}}!", {}) == "Hello !"


def test_extract_variables_unique_ordered():
    assert extract_variables("{{a}} {{b}} {{a}}") == ["a", "b"]


@override_settings(ENABLE_EMAIL_DELIVERY=False)
def test_send_email_stubbed_when_delivery_disabled():
    log = send_email(
        kind=EmailLog.Kind.VISITOR,
        to_email="x@example.com",
        subject="Hi",
        body="Body",
    )
    assert log.status == EmailLog.Status.STUBBED
    assert EmailLog.objects.count() == 1


@override_settings(ENABLE_EMAIL_DELIVERY=False)
def test_confirmation_builder_creates_log():
    from apps.emails.services.confirmation_email_builder import build_confirmation_email

    lead = LeadFactory(email="lead@example.com", visitor_name="Sam")
    log = build_confirmation_email(lead)
    assert log.kind == EmailLog.Kind.CONFIRMATION
    assert log.to_email == "lead@example.com"
    assert "Sam" in log.body


@override_settings(ENABLE_EMAIL_DELIVERY=False)
def test_internal_alert_builder_creates_log():
    from apps.emails.services.internal_alert_builder import build_internal_alert

    lead = LeadFactory(company="ChipCo", tier=1, score=95)
    log = build_internal_alert(lead)
    assert log.kind == EmailLog.Kind.INTERNAL_ALERT
    assert "ChipCo" in log.body


@override_settings(ENABLE_EMAIL_DELIVERY=False)
def test_follow_up_builder_creates_log():
    from apps.emails.services.follow_up_email_builder import build_follow_up_email

    lead = LeadFactory(email="f@example.com", visitor_name="Lee")
    log = build_follow_up_email(lead)
    assert log.kind == EmailLog.Kind.FOLLOW_UP
    assert log.to_email == "f@example.com"
