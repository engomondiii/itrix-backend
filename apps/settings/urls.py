"""Operator settings URL routes (mounted under /api/v1/settings/)."""

from __future__ import annotations

from django.urls import path

from apps.settings.views import NotificationPrefsView, SlaConfigView

app_name = "itrix_settings"

urlpatterns = [
    path("sla/", SlaConfigView.as_view(), name="sla"),
    path("notifications/", NotificationPrefsView.as_view(), name="notifications"),
]
