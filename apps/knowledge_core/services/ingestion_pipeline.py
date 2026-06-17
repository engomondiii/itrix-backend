"""
Ingestion pipeline.

Orchestrates ingesting a single ``KnowledgeDocument``:

    load text → chunk by heading → tag metadata → embed → upsert to Pinecone
    → persist KnowledgeChunk rows → mark COMPLETE (or FAILED with the error).

It is transactional around the DB writes and defensive end-to-end: a failure flips the
document to FAILED and records the message rather than raising out of a request/command.
Works fully offline (deterministic embeddings + no-op upsert) when the AI engine is off.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.knowledge_core.models import IngestionStatus, KnowledgeChunk, KnowledgeDocument
from apps.knowledge_core.services.chunker import chunk_text
from apps.knowledge_core.services.document_loader import load_document_text
from apps.knowledge_core.services.embedder import Embedder
from apps.knowledge_core.services.metadata_tagger import build_chunk_metadata
from apps.knowledge_core.services.namespace_router import normalize_namespace
from apps.knowledge_core.services.pinecone_upserter import PineconeUpserter
from storage.utils import compute_file_hash
from storage.backends import read_file_bytes

logger = logging.getLogger("itrix")


class IngestionResult:
    def __init__(self, *, document, ok: bool, chunk_count: int = 0, error: str = ""):
        self.document = document
        self.ok = ok
        self.chunk_count = chunk_count
        self.error = error

    def to_dict(self) -> dict:
        return {
            "document_id": str(self.document.id),
            "title": self.document.title,
            "ok": self.ok,
            "chunk_count": self.chunk_count,
            "error": self.error,
        }


def ingest_document(document: KnowledgeDocument, *, dry_run: bool = False) -> IngestionResult:
    """Run the full ingestion pipeline for one document."""
    namespace = normalize_namespace(document.namespace)

    if not dry_run:
        document.ingestion_status = IngestionStatus.PROCESSING
        document.ingestion_error = ""
        document.save(update_fields=["ingestion_status", "ingestion_error", "updated_at"])

    try:
        source = document.source_ref
        if not source:
            raise ValueError("Document has no file_path or uploaded_file.")

        text = load_document_text(source)
        chunks = chunk_text(text)
        if not chunks:
            raise ValueError("Document produced no chunks (empty or unreadable).")

        # Content hash for change detection (best-effort).
        try:
            content_hash = compute_file_hash(__import__("io").BytesIO(read_file_bytes(source)))
        except Exception:  # noqa: BLE001
            content_hash = ""

        if dry_run:
            logger.info(
                "[dry-run] %s -> %d chunks in namespace '%s'", document.title, len(chunks), namespace
            )
            return IngestionResult(document=document, ok=True, chunk_count=len(chunks))

        embedder = Embedder()
        vectors_payload: list[dict] = []
        chunk_rows: list[KnowledgeChunk] = []

        texts = [c.text for c in chunks]
        embeddings = embedder.embed(texts)

        for chunk, vector in zip(chunks, embeddings):
            vector_id = f"{document.id}:{chunk.index}"
            row = KnowledgeChunk(
                document=document,
                namespace=namespace,
                disclosure_level=document.disclosure_level,
                chunk_index=chunk.index,
                heading=chunk.heading,
                text=chunk.text,
                token_estimate=chunk.token_estimate,
                vector_id=vector_id,
                embedded=True,
            )
            chunk_rows.append(row)
            vectors_payload.append(
                {
                    "id": vector_id,
                    "values": vector,
                    "metadata": build_chunk_metadata(document=document, chunk=row),
                }
            )

        # Upsert to Pinecone (no-op when disabled).
        PineconeUpserter().upsert(namespace=namespace, vectors=vectors_payload)

        # Persist chunks + finalise document atomically.
        with transaction.atomic():
            document.chunks.all().delete()  # idempotent re-ingest
            KnowledgeChunk.objects.bulk_create(chunk_rows)
            document.ingestion_status = IngestionStatus.COMPLETE
            document.ingestion_error = ""
            document.chunk_count = len(chunk_rows)
            document.content_hash = content_hash
            document.last_ingested_at = timezone.now()
            document.save(
                update_fields=[
                    "ingestion_status",
                    "ingestion_error",
                    "chunk_count",
                    "content_hash",
                    "last_ingested_at",
                    "updated_at",
                ]
            )

        logger.info("Ingested '%s': %d chunks -> namespace '%s'", document.title, len(chunk_rows), namespace)
        return IngestionResult(document=document, ok=True, chunk_count=len(chunk_rows))

    except Exception as exc:  # noqa: BLE001 - convert to a recorded failure
        logger.exception("Ingestion failed for document %s", document.id)
        if not dry_run:
            document.ingestion_status = IngestionStatus.FAILED
            document.ingestion_error = str(exc)[:2000]
            document.save(update_fields=["ingestion_status", "ingestion_error", "updated_at"])
        return IngestionResult(document=document, ok=False, error=str(exc))


def reingest_namespace(namespace: str, *, dry_run: bool = False) -> list[IngestionResult]:
    """Re-ingest every document in a namespace (clears its Pinecone namespace first)."""
    namespace = normalize_namespace(namespace)
    if not dry_run:
        PineconeUpserter().delete_namespace(namespace)
    docs = KnowledgeDocument.objects.filter(namespace=namespace)
    return [ingest_document(doc, dry_run=dry_run) for doc in docs]
