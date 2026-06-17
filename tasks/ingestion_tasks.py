"""
Celery tasks for knowledge ingestion.

Thin wrappers around the ingestion pipeline so ingestion can be queued. When
``ENABLE_CELERY`` is False these run synchronously (eager), so calling ``.delay()`` still
works end-to-end without a broker.
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger("itrix")


@shared_task(name="knowledge.ingest_document")
def ingest_document_task(document_id: str, dry_run: bool = False) -> dict:
    from apps.knowledge_core.models import KnowledgeDocument
    from apps.knowledge_core.services.ingestion_pipeline import ingest_document

    doc = KnowledgeDocument.objects.filter(pk=document_id).first()
    if not doc:
        return {"ok": False, "error": f"No document {document_id}"}
    return ingest_document(doc, dry_run=dry_run).to_dict()


@shared_task(name="knowledge.reingest_namespace")
def reingest_namespace_task(namespace: str, dry_run: bool = False) -> list[dict]:
    from apps.knowledge_core.services.ingestion_pipeline import reingest_namespace

    return [r.to_dict() for r in reingest_namespace(namespace, dry_run=dry_run)]
