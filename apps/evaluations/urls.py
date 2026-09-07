"""Evaluation URLs (mounted under /api/v1/evaluations/) — JWT."""

from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.evaluations.views import EvaluationViewSet
from apps.evaluations.views_core import AlphaCoreOpportunityView

app_name = "evaluations"

router = DefaultRouter(trailing_slash=True)
router.register(r"", EvaluationViewSet, basename="evaluation")

urlpatterns = [
    path(
        "<uuid:evaluation_id>/alpha-core-opportunity/",
        AlphaCoreOpportunityView.as_view(),
        name="alpha-core-opportunity",
    ),
    *router.urls,
]
