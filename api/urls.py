"""
API root — mounts the versioned API.

    /api/v1/   → api.v1.urls
"""

from __future__ import annotations

from django.urls import include, path

urlpatterns = [
    path("v1/", include("api.v1.urls")),
]
