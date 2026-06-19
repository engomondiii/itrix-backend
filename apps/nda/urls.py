"""NDA URLs (mounted under /api/v1/nda/) — JWT.

The router's ``{pk}`` segment carries the **lead id**; the viewset resolves the NDA
via its ``lead`` relation (see ``NDAViewSet.lookup_field``).
"""

from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.nda.views import NDAViewSet

app_name = "nda"

router = DefaultRouter(trailing_slash=True)
router.register(r"", NDAViewSet, basename="nda")

urlpatterns = router.urls
