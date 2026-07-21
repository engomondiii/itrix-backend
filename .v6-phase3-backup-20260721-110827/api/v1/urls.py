"""
itriX API v1 router.

This is the single place every route group is mounted. Phase 1 groups are LIVE.
Phase 2 and Phase 3 groups are listed in their exact final positions but commented
out — when those apps are implemented, uncomment the matching line (and add the app
to ``LOCAL_APPS`` in ``settings/base.py``). Nothing else changes.

LIVE NOW (Phase 1):
    auth/         apps.authentication.urls   (login, logout, me, token/refresh)
    team/         apps.team.urls             (list, retrieve, patch)
    visitors/     apps.visitors.urls         (sessions, room-entry)            PUBLIC
    review/       apps.review.urls           (sessions, prompt, qualify)       PUBLIC

A lightweight ``GET /api/v1/`` index lists the live groups for quick verification.
"""

from __future__ import annotations

from django.http import JsonResponse
from django.urls import include, path

from apps.leads.views import LeadEmailCaptureView
from apps.agents.views import (
    CockpitLeadView,
    CockpitNextActionView,
    ConsoleConversationListView,
    ConsoleMessageView,
)
from apps.result_page.views import ResultPageClientChatView, ResultPageClientView


def api_index(_request):
    """Tiny discovery endpoint — confirms the API is up and lists live groups."""
    return JsonResponse(
        {
            "service": "itrix-backend",
            "version": "v1",
            "phase": 3,
            "live_groups": [
                "auth",
                "team",
                "visitors",
                "review",
                "ai",
                "result-page",
                "lead-capture",
                "knowledge-core",
                "leads",
                "pipeline",
                "follow-up",
                "nda",
                "evaluations",
                "pocs",
                "emails",
                "analytics",
                "templates",
                "reporting",
                "notifications",
                "journey",
                "agents",
                "accounts",
                "client",
                "portal",
                "client-page",
                "conversations",
                "threads",
                "personas",
                "attachments",
                "portal-success",
                "governance",
                "console",
                "cockpit",
                "analytics-pitch",
            ],
            "public_groups": ["visitors", "review", "ai", "result-page", "lead-capture", "client-page", "accounts"],
        }
    )


urlpatterns = [
    path("", api_index, name="api-v1-index"),
    # ── Phase 1 — Foundation, Identity & Public Intake ───────────────────────
    path("auth/", include("apps.authentication.urls")),
    path("team/", include("apps.team.urls")),
    path("visitors/", include("apps.visitors.urls")),       # PUBLIC (Surface 1)
    path("review/", include("apps.review.urls")),           # PUBLIC (Surface 1)
    # ── Phase 1 (v4.0) — Identity, Journey & Agent Runtime ───────────────────
    path("journey/", include("apps.journey.urls")),         # PUBLIC token GET + TEAM lead routes
    path("agents/", include("apps.agents.urls")),           # TEAM (partial: run, behind ENABLE_AGENTS)
    path("", include("apps.clients.urls")),                 # PUBLIC invite claim + CLIENT auth/portal/*
    # ── Phase 2 (v4.0) — Conversation, Realtime & Client Portal ──────────────
    path("client-page/<str:token>/chat/", ResultPageClientChatView.as_view(), name="client-page-chat"),  # PUBLIC token
    path("client-page/<str:token>/", ResultPageClientView.as_view(), name="client-page"),                # PUBLIC token
    path("conversations/", include("apps.conversations.urls")),   # TEAM console reads
    # ── Phase 1 (v6.0) — the conversation spine ──────────────────────────────
    path("threads/", include("apps.conversations.urls_thread")),  # PUBLIC session-scoped
    path("personas/", include("apps.personas.urls")),             # TEAM internal-only
    # ── Phase 2 (v6.0) — attachments + the State 10 customer-success surface ─
    path("attachments/", include("apps.attachments.urls")),       # PUBLIC session-scoped
    path("portal/success/", include("apps.customer_success.urls")),  # CLIENT plane
    # ── Phase 3 (v4.0) — Governance, Console & Cockpit ───────────────────────
    path("governance/", include("apps.governance.urls")),        # TEAM claim-cards + audit
    path("console/conversations/", ConsoleConversationListView.as_view(), name="console-conversations"),
    path("console/conversations/<uuid:conversation_id>/message/", ConsoleMessageView.as_view(), name="console-message"),
    path("cockpit/leads/<uuid:lead_id>/next-action/", CockpitNextActionView.as_view(), name="cockpit-next-action"),
    path("cockpit/leads/<uuid:lead_id>/", CockpitLeadView.as_view(), name="cockpit-lead"),
    # ── Phase 2 — Intelligence Core ──────────────────────────────────────────
    path("ai/", include("apps.ai_engine.urls")),                          # PUBLIC generate-result
    path("result-page/", include("apps.result_page.urls")),              # public GET + JWT generate
    path(
        "lead-capture/email/",
        LeadEmailCaptureView.as_view(),
        name="lead-capture-email",
    ),                                                                    # PUBLIC (from apps.leads.views)
    path("knowledge-core/", include("apps.knowledge_core.urls")),        # JWT
    path("leads/", include("apps.leads.urls")),                          # JWT
    # ── Phase 3 — Operations Layer ───────────────────────────────────────────
    path("pipeline/", include("apps.pipeline.urls")),                # JWT
    path("follow-up/", include("apps.follow_up.urls")),              # JWT
    path("nda/", include("apps.nda.urls")),                          # JWT
    path("evaluations/", include("apps.evaluations.urls")),          # JWT
    path("pocs/", include("apps.pocs.urls")),                        # JWT
    path("emails/", include("apps.emails.urls")),                    # JWT
    path("analytics/", include("apps.analytics.urls")),              # JWT
    path("templates/", include("apps.templates_library.urls")),     # JWT
    path("reporting/", include("apps.reporting.urls")),             # JWT
    path("notifications/", include("apps.notifications.urls")),      # JWT
]
