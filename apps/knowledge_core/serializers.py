"""Knowledge Core serializers (JWT — internal document management)."""

from __future__ import annotations

from rest_framework import serializers

from apps.knowledge_core.models import ClaimRecord, KnowledgeChunk, KnowledgeDocument


class KnowledgeDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeDocument
        fields = [
            "id",
            "title",
            "file_path",
            "uploaded_file",
            "namespace",
            "disclosure_level",
            "ingestion_status",
            "ingestion_error",
            "chunk_count",
            "content_hash",
            "last_ingested_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "ingestion_status",
            "ingestion_error",
            "chunk_count",
            "content_hash",
            "last_ingested_at",
            "created_at",
            "updated_at",
        ]


class KnowledgeChunkSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeChunk
        fields = [
            "id",
            "document",
            "namespace",
            "disclosure_level",
            "chunk_index",
            "heading",
            "text",
            "token_estimate",
            "vector_id",
            "embedded",
        ]
        read_only_fields = fields


class ClaimRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClaimRecord
        fields = [
            "id",
            "document",
            "text",
            "disclosure_level",
            "public_reference",
            "is_prohibited",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
