"""
Client URL routes (Phase 2).

Mounted at the API root (see api/v1/urls.py) so the paths are exactly:
    /api/v1/accounts/invite/{token}/claim/     (PUBLIC — invite claim)
    /api/v1/client/auth/login|token/refresh|logout/   (client auth)
    /api/v1/client/me/                          (CLIENT)
    /api/v1/portal/overview/                    (CLIENT)
    /api/v1/portal/conversations/  ·  {id}/messages/
    /api/v1/portal/documents/  ·  evaluation/  ·  poc/  ·  settings/
"""

from __future__ import annotations

from django.urls import path

from apps.clients.views import (
    ClientLoginView,
    ClientLogoutView,
    ClientMeView,
    ClientSetPasswordView,
    ClientTokenRefreshView,
    InviteClaimView,
    PortalConversationListView,
    PortalConversationMessagesView,
    PortalDocumentsView,
    PortalEvaluationView,
    PortalOverviewView,
    PortalPoCView,
    PortalSettingsView,
)

app_name = "clients"

urlpatterns = [
    # Invite claim (PUBLIC — the token is the credential)
    path("accounts/invite/<str:token>/claim/", InviteClaimView.as_view(), name="invite-claim"),
    # Client auth (client-JWT plane)
    path("client/auth/login/", ClientLoginView.as_view(), name="client-login"),
    path("client/auth/token/refresh/", ClientTokenRefreshView.as_view(), name="client-token-refresh"),
    path("client/auth/password/set/", ClientSetPasswordView.as_view(), name="client-password-set"),
    path("client/auth/logout/", ClientLogoutView.as_view(), name="client-logout"),
    path("client/me/", ClientMeView.as_view(), name="client-me"),
    # Portal data endpoints (CLIENT)
    path("portal/overview/", PortalOverviewView.as_view(), name="portal-overview"),
    path("portal/conversations/", PortalConversationListView.as_view(), name="portal-conversations"),
    path(
        "portal/conversations/<uuid:conversation_id>/messages/",
        PortalConversationMessagesView.as_view(),
        name="portal-conversation-messages",
    ),
    path("portal/documents/", PortalDocumentsView.as_view(), name="portal-documents"),
    path("portal/evaluation/", PortalEvaluationView.as_view(), name="portal-evaluation"),
    path("portal/poc/", PortalPoCView.as_view(), name="portal-poc"),
    path("portal/settings/", PortalSettingsView.as_view(), name="portal-settings"),
]
