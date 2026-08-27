"""AI Engine URLs (mounted under /api/v1/ai/).

``generate-result/`` is retained only as a 410 compatibility tombstone.  Surface 1 now
uses the browser-bound review readiness/access flow.
"""

from __future__ import annotations

from django.urls import path

from apps.ai_engine.views import GenerateResultView

app_name = "ai_engine"

urlpatterns = [
    path("generate-result/", GenerateResultView.as_view(), name="generate-result"),
]
