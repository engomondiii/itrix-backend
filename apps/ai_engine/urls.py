"""AI Engine URLs (mounted under /api/v1/ai/).

Public: generate-result/ (Surface 1 result proxy calls this).
"""

from __future__ import annotations

from django.urls import path

from apps.ai_engine.views import GenerateResultView

app_name = "ai_engine"

urlpatterns = [
    path("generate-result/", GenerateResultView.as_view(), name="generate-result"),
]
