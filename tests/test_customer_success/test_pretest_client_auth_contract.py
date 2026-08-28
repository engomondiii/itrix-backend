"""Customer Success endpoints use the client-JWT plane, including Success Improve."""
from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.clients.tokens import build_tokens_for_client
from apps.customer_success.models import FeedbackPulse

pytestmark = pytest.mark.django_db


GET_PATHS = [
    "/api/v1/portal/success/overview/",
    "/api/v1/portal/success/outcomes/",
    "/api/v1/portal/success/deployments/",
    "/api/v1/portal/success/support/",
    "/api/v1/portal/success/plan/",
    "/api/v1/portal/success/changes/",
    "/api/v1/portal/success/team/",
    "/api/v1/portal/success/knowledge/",
]


def _client_api(client) -> APIClient:
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {build_tokens_for_client(client)['access']}")
    return api


@pytest.mark.parametrize("path", GET_PATHS)
def test_success_get_endpoints_accept_client_jwt(paying_client, path):
    response = _client_api(paying_client).get(path)
    assert response.status_code == 200


def test_success_improve_is_a_real_durable_contract(paying_client):
    response = _client_api(paying_client).post(
        "/api/v1/portal/success/improve/",
        {"message": "Please improve the onboarding documentation for our team."},
        format="json",
    )
    assert response.status_code == 201
    assert response.data["route"] == "training"
    assert response.data["acknowledgement"]
    assert FeedbackPulse.objects.filter(client=paying_client, wants_follow_up=True).count() == 1


def test_team_plane_token_cannot_cross_into_customer_success(auth_client, paying_client):
    for path in ("/api/v1/portal/success/overview/", "/api/v1/portal/success/improve/"):
        response = (
            auth_client.get(path)
            if path.endswith("overview/")
            else auth_client.post(path, {"message": "Please help."}, format="json")
        )
        assert response.status_code in {401, 403}
