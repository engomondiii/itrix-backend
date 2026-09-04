"""Focused portal/auth contract regressions from the latest pre-MVP audit."""
from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.clients.tokens import build_tokens_for_client
from apps.result_page.models import ResultPage
from tests.factories.client_factory import ClientFactory

pytestmark = pytest.mark.django_db


def _client_api(client) -> APIClient:
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {build_tokens_for_client(client)['access']}")
    return api


def test_workspace_briefing_contract_is_client_authenticated_and_public_safe(settings):
    settings.ENABLE_CLIENT_PORTAL = True
    client = ClientFactory()
    client.lead.product_route = "alpha_compute"
    client.lead.save(update_fields=["product_route", "updated_at"])
    ResultPage.objects.create(
        lead=client.lead,
        tier=1,
        score_breakdown={"hidden": 99},
        persona_context={"persona_id": "P015"},
        generation_status=ResultPage.GenerationStatus.READY,
        problem_mirror_structured={"statedFacts": ["A stated workload constraint."]},
        alpha_fit_summary="A client-safe fit summary.",
        diagnosis=[{"observation": "A public-safe diagnosis."}],
        kpi_preview=[{"label": "Latency", "metric": "Measure p95"}],
    )

    anonymous = APIClient().get(reverse("clients:portal-briefing"))
    assert anonymous.status_code in {401, 403}

    response = _client_api(client).get(reverse("clients:portal-briefing"))
    assert response.status_code == 200
    assert set(response.data) == {
        "productRoute", "licensePathway", "sections", "lastUpdated", "updatedNotice"
    }
    assert response.data["licensePathway"] is None
    raw = str(response.data).lower()
    for forbidden in ("score_breakdown", "persona_context", "p015", "hidden"):
        assert forbidden not in raw


def test_portal_next_action_uses_client_jwt_plane(settings):
    settings.ENABLE_CLIENT_PORTAL = True
    client = ClientFactory()
    response = _client_api(client).get(reverse("clients:portal-next-action"))
    assert response.status_code == 200

    unauthenticated = APIClient().get(reverse("clients:portal-next-action"))
    assert unauthenticated.status_code in {401, 403}
