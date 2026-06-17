"""Evaluation URLs (mounted under /api/v1/evaluations/) — JWT."""

from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.evaluations.views import EvaluationViewSet

app_name = "evaluations"

router = DefaultRouter(trailing_slash=True)
router.register(r"", EvaluationViewSet, basename="evaluation")

urlpatterns = router.urls
