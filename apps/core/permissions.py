"""
Permission classes.

Surface 1 (public web) endpoints use ``AllowAny`` (the project default). Surface 2
(dashboard) endpoints opt in to :class:`IsDashboardUser` (any authenticated, active
team member) and the finer role gates below.

Role values come from ``apps.authentication.models.User.Role``
(ADMIN / ASSESSMENT / SPECIALIST / VIEWER). We read them by string so this module
never imports the user model at import time (avoids app-loading order issues).
"""

from __future__ import annotations

from rest_framework.permissions import SAFE_METHODS, BasePermission

ROLE_ADMIN = "ADMIN"
ROLE_ASSESSMENT = "ASSESSMENT"
ROLE_SPECIALIST = "SPECIALIST"
ROLE_VIEWER = "VIEWER"


def _is_active_team_member(user) -> bool:
    return bool(user and user.is_authenticated and getattr(user, "is_active", False))


class IsDashboardUser(BasePermission):
    """Any authenticated, active team member may use the dashboard API."""

    message = "Authentication as an active iTrix team member is required."

    def has_permission(self, request, view) -> bool:
        return _is_active_team_member(request.user)


class IsAdminRole(BasePermission):
    """Only ADMIN users (team & SLA configuration, destructive ops)."""

    message = "Administrator role required."

    def has_permission(self, request, view) -> bool:
        return _is_active_team_member(request.user) and request.user.role == ROLE_ADMIN


class IsAdminOrReadOnly(BasePermission):
    """Read for any team member, writes only for ADMIN."""

    def has_permission(self, request, view) -> bool:
        if not _is_active_team_member(request.user):
            return False
        if request.method in SAFE_METHODS:
            return True
        return request.user.role == ROLE_ADMIN


class IsNotViewer(BasePermission):
    """
    Block VIEWER role from write actions.

    VIEWERs can read everything in the dashboard but must not mutate leads,
    pipeline, NDAs, etc. Use alongside ``IsDashboardUser``.
    """

    message = "This action is not available to viewer accounts."

    def has_permission(self, request, view) -> bool:
        if not _is_active_team_member(request.user):
            return False
        if request.method in SAFE_METHODS:
            return True
        return request.user.role != ROLE_VIEWER


class IsSelfOrAdmin(BasePermission):
    """Object-level: a user may act on their own record; ADMIN on anyone's."""

    def has_object_permission(self, request, view, obj) -> bool:
        if not _is_active_team_member(request.user):
            return False
        if request.user.role == ROLE_ADMIN:
            return True
        owner_id = getattr(obj, "id", None)
        return owner_id is not None and owner_id == request.user.id
