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


class IsGovernanceAdmin(BasePermission):
    """
    Governance administration (claim-card writes, approval actions) is restricted to
    ADMIN and ASSESSMENT roles — the people accountable for approved wording. VIEWER and
    SPECIALIST may read the queue but not resolve it.
    """

    message = "Governance administration requires an ADMIN or ASSESSMENT role."

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated and getattr(user, "is_active", False)):
            return False
        return getattr(user, "role", "") in ("ADMIN", "ASSESSMENT")


class IsJourneyController(BasePermission):
    """
    Guarded manual journey advance (POST journey/leads/{id}/advance/) is restricted to
    ADMIN and ASSESSMENT roles, since a manual transition can trigger reveals + fan-out.
    """

    message = "Advancing a lead's journey requires an ADMIN or ASSESSMENT role."

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated and getattr(user, "is_active", False)):
            return False
        return getattr(user, "role", "") in ("ADMIN", "ASSESSMENT")
