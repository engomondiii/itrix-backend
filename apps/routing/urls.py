"""Routing URLs.

Not mounted in the public API for Phase 2 (routing runs inside the review flow).
Provided for completeness and internal use.
"""

from __future__ import annotations

from django.urls import path

from apps.routing.views import RoutingPreviewView

app_name = "routing"

urlpatterns = [
    path("preview/", RoutingPreviewView.as_view(), name="routing-preview"),
]
