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

from apps.clients.views_auth import (
    ClientPasswordChangeView,
    InviteLookupView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    RegisterView,
    VerifyEmailConfirmView,
    VerifyEmailResendView,
)
from apps.clients.views import (
    PortalNextBestActionView,
    PortalBriefingView,
    PortalWSTicketView,
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
    PortalNdaRequestView,
    PortalSettingsView,
    PortalTeamInviteView,
)

app_name = "clients"

urlpatterns = [
    # ── v7.2 Phase 4 — the authentication surface (PUBLIC) ───────────────────
    # Mounted under `auth/` to match the proxies `itrix-web` Phase 4 already calls. The
    # shipped `client/auth/*` names below are NOT renamed: a rename would break a deployed
    # surface to satisfy a document (Backend v7.2 §14).
    path("auth/register/", RegisterView.as_view(), name="auth-register"),
    path("auth/password-reset/request/", PasswordResetRequestView.as_view(), name="auth-reset-request"),
    path("auth/password-reset/confirm/", PasswordResetConfirmView.as_view(), name="auth-reset-confirm"),
    path("auth/invite/lookup/", InviteLookupView.as_view(), name="auth-invite-lookup"),
    path("auth/verify-email/confirm/", VerifyEmailConfirmView.as_view(), name="auth-verify-confirm"),
    path("auth/verify-email/resend/", VerifyEmailResendView.as_view(), name="auth-verify-resend"),
    # CLIENT plane — the authenticated change. Distinct from `client/auth/password/set/`,
    # which redeems a single-use first-time token.
    path("client/auth/password/", ClientPasswordChangeView.as_view(), name="client-password-change"),
    # Invite claim (PUBLIC — the token is the credential)
    path("accounts/invite/<str:token>/claim/", InviteClaimView.as_view(), name="invite-claim"),
    # Client auth (client-JWT plane)
    path("client/auth/login/", ClientLoginView.as_view(), name="client-login"),
    path("client/auth/token/refresh/", ClientTokenRefreshView.as_view(), name="client-token-refresh"),
    path("client/auth/password/set/", ClientSetPasswordView.as_view(), name="client-password-set"),
    path("client/auth/logout/", ClientLogoutView.as_view(), name="client-logout"),
    path("client/me/", ClientMeView.as_view(), name="client-me"),
    # Portal data endpoints (CLIENT)
    path("portal/ws-ticket/", PortalWSTicketView.as_view(), name="portal-ws-ticket"),
    path("portal/overview/", PortalOverviewView.as_view(), name="portal-overview"),
    path("portal/briefing/", PortalBriefingView.as_view(), name="portal-briefing"),
    path("portal/conversations/", PortalConversationListView.as_view(), name="portal-conversations"),
    path(
        "portal/conversations/<uuid:conversation_id>/messages/",
        PortalConversationMessagesView.as_view(),
        name="portal-conversation-messages",
    ),
    path("portal/documents/", PortalDocumentsView.as_view(), name="portal-documents"),
    path("portal/evaluation/", PortalEvaluationView.as_view(), name="portal-evaluation"),
    path("portal/poc/", PortalPoCView.as_view(), name="portal-poc"),
    path("portal/nda/request/", PortalNdaRequestView.as_view(), name="portal-nda-request"),
    path("portal/settings/", PortalSettingsView.as_view(), name="portal-settings"),
    path(
        "portal/settings/team/invite/",
        PortalTeamInviteView.as_view(),
        name="portal-team-invite",
    ),
    path("portal/next-action/", PortalNextBestActionView.as_view(), name="portal-next-action"),
]
