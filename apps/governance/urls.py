"""
Governance URL routes (mounted under /api/v1/governance/) — TEAM.

    GET/POST  claim-cards/
    GET/PATCH claim-cards/{id}/
    GET       audit/
"""

from __future__ import annotations

from django.urls import path

from apps.governance.views import (
    ClaimCardDetailView,
    ClaimCardListCreateView,
    GovernanceAuditView,
)

app_name = "governance"

urlpatterns = [
    path("claim-cards/", ClaimCardListCreateView.as_view(), name="claim-cards"),
    path("claim-cards/<uuid:card_id>/", ClaimCardDetailView.as_view(), name="claim-card-detail"),
    path("audit/", GovernanceAuditView.as_view(), name="audit"),
]
