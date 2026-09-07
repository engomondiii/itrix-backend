"""Lead URL routes (mounted under /api/v1/leads/) — JWT (Surface 2).

The public lead-capture/email/ endpoint is wired separately in api/v1/urls.py from
apps.leads.views.LeadEmailCaptureView (there is no separate lead-capture app).
"""

from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.leads.views import LeadViewSet
from apps.leads.views_entitlement import ASTOPEntitlementLifecycleView
from apps.leads.views_lo import GovernedLOTermsView
from apps.leads.views_readiness import ASTOPReadinessView
from apps.leads.views_review import TrustReviewView

app_name = "leads"

router = DefaultRouter(trailing_slash=True)
router.register(r"", LeadViewSet, basename="lead")

urlpatterns = [
    path(
        "<uuid:lead_id>/trust-review/",
        TrustReviewView.as_view(),
        name="trust-review",
    ),
    path(
        "<uuid:lead_id>/astop-entitlement/",
        ASTOPEntitlementLifecycleView.as_view(),
        name="astop-entitlement-lifecycle",
    ),
    path(
        "<uuid:lead_id>/astop-lo-terms/",
        GovernedLOTermsView.as_view(),
        name="astop-lo-terms",
    ),
    path(
        "<uuid:lead_id>/astop-readiness/",
        ASTOPReadinessView.as_view(),
        name="astop-readiness",
    ),
    *router.urls,
]
