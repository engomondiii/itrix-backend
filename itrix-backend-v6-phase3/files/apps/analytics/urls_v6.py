"""v6.0 Phase 3 analytics routes (mounted at /api/v1/analytics/) — TEAM."""

from __future__ import annotations

from django.urls import path

from apps.analytics.views_v6 import (
    AttachmentAnalyticsView,
    ConversationAnalyticsView,
    CustomerHealthAnalyticsView,
    OutcomeProgressAnalyticsView,
    StreamingAnalyticsView,
    SupportLoadAnalyticsView,
)

urlpatterns = [
    path("customers/", CustomerHealthAnalyticsView.as_view(), name="analytics-customers"),
    path("support/", SupportLoadAnalyticsView.as_view(), name="analytics-support"),
    path("outcomes/", OutcomeProgressAnalyticsView.as_view(), name="analytics-outcomes"),
    path("conversations/", ConversationAnalyticsView.as_view(), name="analytics-conversations"),
    path("attachments/", AttachmentAnalyticsView.as_view(), name="analytics-attachments"),
    path("streaming/", StreamingAnalyticsView.as_view(), name="analytics-streaming"),
]
