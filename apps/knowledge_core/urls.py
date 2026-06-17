"""Knowledge Core URLs (mounted under /api/v1/knowledge-core/) — JWT."""

from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.knowledge_core.views import KnowledgeCoreStatusView, KnowledgeDocumentViewSet

app_name = "knowledge_core"

router = DefaultRouter(trailing_slash=True)
router.register(r"documents", KnowledgeDocumentViewSet, basename="knowledge-document")

urlpatterns = [
    path("status/", KnowledgeCoreStatusView.as_view(), name="knowledge-status"),
    *router.urls,
]
