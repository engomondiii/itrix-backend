"""Email URLs (mounted under /api/v1/emails/) — JWT."""

from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.emails.views import EmailViewSet

app_name = "emails"

router = DefaultRouter(trailing_slash=True)
router.register(r"", EmailViewSet, basename="email")

urlpatterns = router.urls
