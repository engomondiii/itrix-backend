"""
Follow-up views (JWT — Surface 2).

    GET  /follow-up/                list pending+snoozed tasks (sorted by due)
    GET  /follow-up/overdue/        overdue tasks
    GET  /follow-up/today/          tasks due today
    POST /follow-up/{id}/complete/  mark complete
    POST /follow-up/{id}/snooze/    snooze by {hours} (default 24)
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import IsDashboardUser, IsNotViewer
from apps.follow_up.models import FollowUpStatus, FollowUpTask
from apps.follow_up.serializers import FollowUpTaskSerializer, SnoozeSerializer
from apps.follow_up.services.sla_breach_checker import find_overdue


class FollowUpViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = FollowUpTask.objects.all().select_related("owner", "lead")
    serializer_class = FollowUpTaskSerializer
    permission_classes = [IsAuthenticated, IsDashboardUser]

    def _open_qs(self):
        return self.get_queryset().filter(
            status__in=[FollowUpStatus.PENDING, FollowUpStatus.SNOOZED]
        )

    def list(self, request, *args, **kwargs):
        qs = self._open_qs().order_by("due_at")
        data = FollowUpTaskSerializer(qs, many=True).data
        return Response({"results": data, "count": len(data)})

    @action(detail=False, methods=["get"])
    def overdue(self, request):
        qs = find_overdue().order_by("due_at")
        data = FollowUpTaskSerializer(qs, many=True).data
        return Response({"results": data, "count": len(data)})

    @action(detail=False, methods=["get"])
    def today(self, request):
        now = timezone.now()
        end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        qs = self._open_qs().filter(due_at__gte=now, due_at__lte=end).order_by("due_at")
        data = FollowUpTaskSerializer(qs, many=True).data
        return Response({"results": data, "count": len(data)})

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsDashboardUser, IsNotViewer])
    def complete(self, request, pk=None):
        task = self.get_object()
        task.status = FollowUpStatus.COMPLETED
        task.completed_at = timezone.now()
        task.save(update_fields=["status", "completed_at", "updated_at"])
        return Response(FollowUpTaskSerializer(task).data)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsDashboardUser, IsNotViewer])
    def snooze(self, request, pk=None):
        serializer = SnoozeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = self.get_object()
        task.snoozed_until = timezone.now() + timedelta(hours=serializer.validated_data["hours"])
        task.status = FollowUpStatus.SNOOZED
        task.breach_notified = False  # reset so a future breach re-notifies
        task.save(update_fields=["snoozed_until", "status", "breach_notified", "updated_at"])
        return Response(FollowUpTaskSerializer(task).data)
