"""Follow-up URLs (mounted under /api/v1/follow-up/) — JWT."""

from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.follow_up.views import FollowUpViewSet

app_name = "follow_up"

router = DefaultRouter(trailing_slash=True)
router.register(r"", FollowUpViewSet, basename="follow-up")

urlpatterns = router.urls
