"""Team URL routes (mounted under /api/v1/team/)."""

from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.team.views import TeamMemberViewSet

app_name = "team"

router = DefaultRouter(trailing_slash=True)
router.register(r"", TeamMemberViewSet, basename="team")

urlpatterns = router.urls
