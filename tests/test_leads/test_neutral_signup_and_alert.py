"""A new account is a neutral prospect, not fabricated product/commercial qualification."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.emails.services.internal_alert_builder import build_internal_alert
from apps.leads.models import ASTOPEngagement, Lead, ProductRouteCode

pytestmark = pytest.mark.django_db

ASSENT = [
    {"slug": "terms", "version": "1.2", "effective": "2026-07-30"},
    {"slug": "privacy", "version": "1.2", "effective": "2026-07-30"},
]


def test_fresh_open_signup_remains_product_and_commercially_neutral(api_client, settings):
    settings.ENABLE_OPEN_SIGNUP = True
    response = api_client.post(
        reverse("clients:auth-register"),
        {
            "email": "neutral.signup@example.com",
            "password": "a-long-enough-password",
            "fullName": "Neutral Signup",
            "organization": "Example Org",
            "role": "Engineer",
            "assent": ASSENT,
        },
        format="json",
    )
    assert response.status_code == 202
    lead = Lead.objects.get(email="neutral.signup@example.com")
    assert lead.product_route == ProductRouteCode.UNDETERMINED
    assert lead.product_route_display == "Not yet assessed"
    assert lead.commercial_path == "none"
    assert lead.commercial_path_display == "Not yet determined"
    assert lead.current_marketing_stage == "discovery"
    assert not ASTOPEngagement.objects.filter(lead=lead).exists()
    # ALPHA opportunities are represented by Evaluation records, not merely labels.
    from apps.evaluations.models import Evaluation

    assert not Evaluation.objects.filter(lead=lead).exists()


def test_neutral_internal_alert_uses_neutral_wording(settings):
    lead = Lead(
        company="Neutral Org",
        email="neutral@example.com",
        product_route=ProductRouteCode.UNDETERMINED,
        commercial_path="none",
        score=0,
        tier=4,
        primary_pain="",
    )
    with patch("apps.emails.services.internal_alert_builder.send_email") as send:
        send.return_value = object()
        build_internal_alert(lead)
    body = send.call_args.kwargs["body"]
    assert "Product route: Not yet assessed" in body
    assert "Commercial   : Not yet determined" in body
    assert "Product route: ALPHA Compute" not in body
    assert "Commercial   : Non-Exclusive" not in body
