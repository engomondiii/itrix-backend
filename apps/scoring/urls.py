"""Scoring URLs.

Not mounted in the public API for Phase 2 (scoring runs inside the review flow).
Provided for completeness and internal use.
"""

from __future__ import annotations

from django.urls import path

from apps.scoring.views import ScorePreviewView

app_name = "scoring"

urlpatterns = [
    path("preview/", ScorePreviewView.as_view(), name="score-preview"),
]
