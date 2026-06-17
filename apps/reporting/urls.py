"""Reporting URLs (mounted under /api/v1/reporting/) — JWT."""

from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.reporting.views import ReportingViewSet

app_name = "reporting"

router = DefaultRouter(trailing_slash=True)
router.register(r"", ReportingViewSet, basename="report")

urlpatterns = router.urls
