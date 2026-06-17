"""
Team views (JWT-protected — Surface 2).

    GET    /api/v1/team/          list team members
    GET    /api/v1/team/{id}/     retrieve one
    PATCH  /api/v1/team/{id}/     update (display role / name / avatar / active)

Reads are open to any authenticated team member; writes require ADMIN.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticated

from apps.core.permissions import IsAdminOrReadOnly, IsDashboardUser
from apps.team.serializers import TeamMemberSerializer, TeamMemberUpdateSerializer

User = get_user_model()


class TeamMemberViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = User.objects.all().order_by("name", "email")
    permission_classes = [IsAuthenticated, IsDashboardUser, IsAdminOrReadOnly]
    http_method_names = ["get", "patch", "head", "options"]

    filterset_fields = ["role", "team_role", "is_active"]
    search_fields = ["name", "email"]
    ordering_fields = ["name", "email", "created_at"]

    def get_serializer_class(self):
        if self.request.method == "PATCH":
            return TeamMemberUpdateSerializer
        return TeamMemberSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        active = self.request.query_params.get("active")
        if active is not None:
            qs = qs.filter(is_active=active.lower() in {"1", "true", "yes"})
        return qs
