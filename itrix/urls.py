"""
Root URL configuration.

    /healthz  → process liveness only; deliberately no dependency checks
    /readyz   → bounded readiness; verifies critical relational DB connectivity
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.db import connection
from django.http import JsonResponse
from django.urls import include, path

logger = logging.getLogger("itrix")


def healthz(_request):
    """Liveness probe — 200 when the web process can answer HTTP."""
    return JsonResponse({"status": "ok", "service": "itrix-backend"})


def readyz(_request):
    """Readiness probe for dependencies required by ordinary MVP request serving.

    The relational database is load-bearing for identity, conversations, governance and
    Knowledge metadata. Redis/realtime is intentionally not included: realtime is an
    optional transport with polling/degraded paths, so a Redis incident must not cause a
    healthy HTTP application to be restarted. LLM/Pinecone are likewise excluded because
    they have bounded failure/fallback behavior and are too volatile for a process probe.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:  # noqa: BLE001 - never expose database exception details
        logger.warning("readiness database check failed")
        return JsonResponse(
            {"status": "not_ready", "checks": {"database": "unavailable"}},
            status=503,
        )
    return JsonResponse({"status": "ready", "checks": {"database": "ok"}})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthz, name="healthz"),
    path("readyz", readyz, name="readyz"),
    path("api/", include("api.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
