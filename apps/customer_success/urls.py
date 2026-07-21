"""Customer-success routes (mounted at /api/v1/portal/success/) — CLIENT plane."""

from __future__ import annotations

from django.urls import path

from apps.customer_success.views import (
    ChangesView,
    DeploymentsView,
    FeedbackView,
    KnowledgeView,
    OutcomesView,
    RelationshipTeamView,
    SuccessOverviewView,
    SuccessPlanView,
    SupportView,
)

app_name = "customer_success"

urlpatterns = [
    path("overview/", SuccessOverviewView.as_view(), name="success-overview"),
    path("outcomes/", OutcomesView.as_view(), name="success-outcomes"),
    path("deployments/", DeploymentsView.as_view(), name="success-deployments"),
    path("support/", SupportView.as_view(), name="success-support"),
    path("plan/", SuccessPlanView.as_view(), name="success-plan"),
    path("changes/", ChangesView.as_view(), name="success-changes"),
    path("team/", RelationshipTeamView.as_view(), name="success-team"),
    path("knowledge/", KnowledgeView.as_view(), name="success-knowledge"),
    # WRITE ONLY — no GET counterpart, by design (§12I).
    path("feedback/", FeedbackView.as_view(), name="success-feedback"),
]
