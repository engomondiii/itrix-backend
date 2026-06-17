"""Pipeline URLs (mounted under /api/v1/pipeline/) — JWT."""

from __future__ import annotations

from django.urls import path

from apps.pipeline.views import PipelineBoardView

app_name = "pipeline"

urlpatterns = [
    path("", PipelineBoardView.as_view(), name="pipeline-board"),
]
