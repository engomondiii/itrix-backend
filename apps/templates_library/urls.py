"""Template URLs (mounted under /api/v1/templates/) — JWT."""

from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.templates_library.views import TemplateViewSet

app_name = "templates_library"

router = DefaultRouter(trailing_slash=True)
router.register(r"", TemplateViewSet, basename="template")

urlpatterns = router.urls
