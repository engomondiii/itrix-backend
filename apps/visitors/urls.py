"""Visitor URL routes (mounted under /api/v1/visitors/) — PUBLIC."""

from __future__ import annotations

from django.urls import path

from apps.visitors.views import RoomEntryView, VisitorSessionCreateView

app_name = "visitors"

urlpatterns = [
    path("sessions/", VisitorSessionCreateView.as_view(), name="session-create"),
    path(
        "sessions/<uuid:session_id>/room-entry/",
        RoomEntryView.as_view(),
        name="room-entry",
    ),
]
