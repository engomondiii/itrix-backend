"""
Notification views (JWT — Surface 2).

    GET  /notifications/                 list (most recent first); ?unread=true to filter
    POST /notifications/{id}/read/       mark one read
    POST /notifications/read-all/        mark all read
"""

from __future__ import annotations

from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import IsDashboardUser
from apps.notifications.models import Notification
from apps.notifications.serializers import NotificationSerializer
from apps.notifications.services.notification_dispatcher import mark_read


class NotificationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated, IsDashboardUser]

    def get_queryset(self):
        qs = super().get_queryset()
        unread = str(self.request.query_params.get("unread", "")).lower() in {"1", "true", "yes"}
        if unread:
            qs = qs.filter(read=False)
        return qs

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        data = NotificationSerializer(qs, many=True).data
        unread_count = self.get_queryset().filter(read=False).count() if not request.query_params.get("unread") else len(data)
        return Response({"results": data, "count": len(data), "unreadCount": unread_count})

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        notification = self.get_object()
        mark_read(notification)
        return Response(NotificationSerializer(notification).data)

    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        Notification.objects.filter(read=False).update(read=True)
        return Response({"ok": True})
