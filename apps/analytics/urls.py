"""Analytics URLs (mounted under /api/v1/analytics/) — JWT."""

from __future__ import annotations

from django.urls import path

from apps.analytics.views import AnalyticsView

app_name = "analytics"

urlpatterns = [
    path("", AnalyticsView.as_view(), name="analytics"),
]
