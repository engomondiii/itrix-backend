"""
Journey URL routes.

Mounted under /api/v1/journey/ (see api/v1/urls.py). The token route is PUBLIC; the
lead routes are TEAM-guarded (IsDashboardUser).

    GET  journey/{token}/
    GET  journey/leads/{id}/
    POST journey/leads/{id}/advance/
"""

from __future__ import annotations

from django.urls import path

from apps.journey.views import JourneyAdvanceView, JourneyByTokenView, JourneyLeadView

app_name = "journey"

urlpatterns = [
    path("leads/<uuid:lead_id>/advance/", JourneyAdvanceView.as_view(), name="lead-advance"),
    path("leads/<uuid:lead_id>/", JourneyLeadView.as_view(), name="lead-journey"),
    path("<str:token>/", JourneyByTokenView.as_view(), name="by-token"),
]
