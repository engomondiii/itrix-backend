"""
Root URL configuration.

    /admin/   → Django admin
    /api/     → versioned REST API (api/urls.py mounts v1)
    /healthz  → lightweight liveness probe (no DB hit) for Railway/Docker
"""

from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def healthz(_request):
    """Liveness probe — returns 200 without touching the database."""
    return JsonResponse({"status": "ok", "service": "itrix-backend"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthz, name="healthz"),
    path("api/", include("api.urls")),
]

# Serve uploaded media in development (production uses WhiteNoise/S3).
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
