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
                "settings",
            ],
            "public_groups": ["visitors", "review", "ai", "result-page", "lead-capture"],
        }
    )


urlpatterns = [
    path("", api_index, name="api-v1-index"),
    # ── Phase 1 — Foundation, Identity & Public Intake ───────────────────────
    path("auth/", include("apps.authentication.urls")),
    path("team/", include("apps.team.urls")),
    path("visitors/", include("apps.visitors.urls")),       # PUBLIC (Surface 1)
    path("review/", include("apps.review.urls")),           # PUBLIC (Surface 1)
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
    path("settings/", include("apps.settings.urls")),                # JWT (SLA + notification prefs)
]
