"""Notification URLs (mounted under /api/v1/notifications/) — JWT."""

from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.notifications.views import NotificationViewSet

app_name = "notifications"

router = DefaultRouter(trailing_slash=True)
router.register(r"", NotificationViewSet, basename="notification")

urlpatterns = router.urls
