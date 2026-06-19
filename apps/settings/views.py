"""
Operator settings views (JWT-protected — Surface 2).

    GET   /api/v1/settings/sla/             -> { "1": n, "2": n, "3": n, "4": n|null }
    PATCH /api/v1/settings/sla/             (ADMIN) partial update of the SLA map
    GET   /api/v1/settings/notifications/   -> { tier1, sla, nda, weekly }
    PATCH /api/v1/settings/notifications/   partial update (per current user)

SLA thresholds are org-wide config, so writes require ADMIN; reads are open to any
team member. Notification preferences are personal to the requesting user.
"""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsAdminOrReadOnly, IsDashboardUser
from apps.settings.models import NotificationPreference, SlaThresholds
from apps.settings.serializers import NotificationPrefsSerializer, SlaConfigSerializer


class SlaConfigView(APIView):
    """Org-wide per-tier SLA thresholds (singleton)."""

    permission_classes = [IsAuthenticated, IsDashboardUser, IsAdminOrReadOnly]

    def get(self, request):
        return Response(SlaConfigSerializer(SlaThresholds.load()).data)

    def patch(self, request):
        instance = SlaThresholds.load()
        serializer = SlaConfigSerializer(instance=instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(SlaConfigSerializer(instance).data)


class NotificationPrefsView(APIView):
    """The current operator's notification toggles."""

    permission_classes = [IsAuthenticated, IsDashboardUser]

    def get(self, request):
        prefs = NotificationPreference.for_user(request.user)
        return Response(NotificationPrefsSerializer(prefs).data)

    def patch(self, request):
        prefs = NotificationPreference.for_user(request.user)
        serializer = NotificationPrefsSerializer(
            instance=prefs, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
