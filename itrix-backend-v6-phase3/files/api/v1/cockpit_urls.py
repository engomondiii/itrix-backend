"""
Cockpit routes (mounted at /api/v1/cockpit/) — TEAM PLANE ONLY (Backend v6.0 §Phase 3).

    cockpit/customers/   the customer health board
    cockpit/threads/     conversation metrics
    cockpit/attachments/ attachment metrics
    cockpit/streaming/   streaming-governance telemetry

Every one of these reads §10.5 internal-only material. They are mounted here, behind
team-JWT, and nowhere else.

The existing cockpit/leads/* routes stay where they are in api/v1/urls.py; this module
adds only the Phase-3 aggregates so the two sets can be reviewed independently.
"""

from __future__ import annotations

from django.urls import path

from apps.analytics.views_v6 import (
    AttachmentAnalyticsView,
    ConversationAnalyticsView,
    CustomerHealthAnalyticsView,
    StreamingAnalyticsView,
)

app_name = "cockpit"

urlpatterns = [
    path("customers/", CustomerHealthAnalyticsView.as_view(), name="cockpit-customers"),
    path("threads/", ConversationAnalyticsView.as_view(), name="cockpit-threads"),
    path("attachments/", AttachmentAnalyticsView.as_view(), name="cockpit-attachments"),
    path("streaming/", StreamingAnalyticsView.as_view(), name="cockpit-streaming"),
]
