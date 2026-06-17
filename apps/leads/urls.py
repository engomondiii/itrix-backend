"""Lead URL routes (mounted under /api/v1/leads/) — JWT (Surface 2).

The public lead-capture/email/ endpoint is wired separately in api/v1/urls.py from
apps.leads.views.LeadEmailCaptureView (there is no separate lead-capture app).
"""

from __future__ import annotations

from rest_framework.routers import DefaultRouter

from apps.leads.views import LeadViewSet

app_name = "leads"

router = DefaultRouter(trailing_slash=True)
router.register(r"", LeadViewSet, basename="lead")

urlpatterns = router.urls
