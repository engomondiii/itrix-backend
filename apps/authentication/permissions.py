"""
Authentication-app permissions.

Re-exports the shared dashboard permissions from ``apps.core.permissions`` so views
in this app can import locally, and adds ``IsAuthenticatedTeamMember`` as a clear
alias used by the auth views.
"""

from __future__ import annotations

from apps.core.permissions import (  # noqa: F401 (re-exported)
    IsAdminRole,
    IsDashboardUser,
    IsNotViewer,
)
from rest_framework.permissions import BasePermission


class IsAuthenticatedTeamMember(BasePermission):
    message = "You must be signed in as an active team member."

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.is_active)
