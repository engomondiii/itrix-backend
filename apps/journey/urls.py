"""
Journey URL routes.

Mounted under /api/v1/journey/ (see api/v1/urls.py). The token route is PUBLIC; the
lead routes are TEAM-guarded (IsDashboardUser).

    GET  journey/overview/
    GET  journey/{token}/
    GET  journey/leads/{id}/
    POST journey/leads/{id}/advance/
"""

from __future__ import annotations

from django.urls import path

from apps.journey.views import (
    JourneyAdvanceView,
    JourneyByTokenView,
    JourneyLeadView,
    JourneyOverviewView,
)

app_name = "journey"

urlpatterns = [
    # `overview/` must precede the `<str:token>/` catch-all, which would otherwise
    # swallow it and try to verify "overview" as a capability token.
    path("overview/", JourneyOverviewView.as_view(), name="overview"),
    path("leads/<uuid:lead_id>/advance/", JourneyAdvanceView.as_view(), name="lead-advance"),
    path("leads/<uuid:lead_id>/", JourneyLeadView.as_view(), name="lead-journey"),
    path("<str:token>/", JourneyByTokenView.as_view(), name="by-token"),
]
