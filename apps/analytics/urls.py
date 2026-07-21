"""Analytics URLs (mounted under /api/v1/analytics/) — JWT."""

from __future__ import annotations

from django.urls import path

from apps.analytics.urls_v6 import urlpatterns as v6_urlpatterns
from apps.analytics.views import AnalyticsView, PitchAnalyticsView

app_name = "analytics"

urlpatterns = [
    path("", AnalyticsView.as_view(), name="analytics"),
    path("pitch/", PitchAnalyticsView.as_view(), name="analytics-pitch"),
    # ── v6.0 Phase 3 aggregates (TEAM plane only) ────────────────────────────
    *v6_urlpatterns,
]
