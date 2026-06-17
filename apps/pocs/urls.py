"""PoC URLs (mounted under /api/v1/pocs/) — JWT."""

from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.pocs.views import PoCViewSet

app_name = "pocs"

router = DefaultRouter(trailing_slash=True)
router.register(r"", PoCViewSet, basename="poc")

urlpatterns = router.urls
