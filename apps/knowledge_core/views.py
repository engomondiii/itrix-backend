"""
Knowledge Core views (JWT — internal document management).

    GET/POST       /knowledge-core/documents/
    GET/PATCH/DEL  /knowledge-core/documents/{id}/
    POST           /knowledge-core/documents/{id}/ingest/   trigger ingestion (sync)
    GET            /knowledge-core/documents/{id}/chunks/   list a doc's chunks
    GET            /knowledge-core/status/                  ingestion summary counts

Ingestion runs through the pipeline (which is fully functional offline). Writes require
a non-viewer; ADMIN may delete.
"""

from __future__ import annotations

from django.db.models import Count
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsAdminOrReadOnly, IsDashboardUser, IsNotViewer
from apps.knowledge_core.models import IngestionStatus, KnowledgeChunk, KnowledgeDocument
from apps.knowledge_core.serializers import (
    KnowledgeChunkSerializer,
    KnowledgeDocumentSerializer,
)
from apps.knowledge_core.services.ingestion_pipeline import ingest_document


class KnowledgeDocumentViewSet(viewsets.ModelViewSet):
    queryset = KnowledgeDocument.objects.all().order_by("-created_at")
    serializer_class = KnowledgeDocumentSerializer
    permission_classes = [IsAuthenticated, IsDashboardUser]
    filterset_fields = ["namespace", "disclosure_level", "ingestion_status"]
    search_fields = ["title", "file_path", "namespace"]
    ordering_fields = ["created_at", "title", "ingestion_status"]

    def get_permissions(self):
        if self.action in {"create", "update", "partial_update", "ingest"}:
            return [IsAuthenticated(), IsDashboardUser(), IsNotViewer()]
        if self.action == "destroy":
            return [IsAuthenticated(), IsDashboardUser(), IsAdminOrReadOnly()]
        return super().get_permissions()

    @action(detail=True, methods=["post"])
    def ingest(self, request, pk=None):
        document = self.get_object()
        dry_run = str(request.query_params.get("dry_run", "")).lower() in {"1", "true", "yes"}
        result = ingest_document(document, dry_run=dry_run)
        code = http_status.HTTP_200_OK if result.ok else http_status.HTTP_502_BAD_GATEWAY
        return Response(result.to_dict(), status=code)

    @action(detail=True, methods=["get"])
    def chunks(self, request, pk=None):
        document = self.get_object()
        qs = document.chunks.all().order_by("chunk_index")
        return Response(KnowledgeChunkSerializer(qs, many=True).data)


class KnowledgeCoreStatusView(APIView):
    """Ingestion summary counts (handy for the dashboard / validation)."""

    permission_classes = [IsAuthenticated, IsDashboardUser]

    def get(self, request):
        by_status = {
            row["ingestion_status"]: row["n"]
            for row in KnowledgeDocument.objects.values("ingestion_status").annotate(n=Count("id"))
        }
        return Response(
            {
                "documents": KnowledgeDocument.objects.count(),
                "chunks": KnowledgeChunk.objects.count(),
                "by_status": {s.value: by_status.get(s.value, 0) for s in IngestionStatus},
            }
        )
