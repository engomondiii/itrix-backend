"""
``python manage.py ingest_documents``

Ingests knowledge documents through the pipeline.

Options:
    --all-pending          ingest only PENDING documents
    --all-failed           ingest only FAILED documents
    --document-id <uuid>   ingest a single document
    --dry-run              parse + chunk only; no embed/upsert/persist

With no selection flags, ingests all PENDING and FAILED documents (the default the
spec describes).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.knowledge_core.models import IngestionStatus, KnowledgeDocument
from apps.knowledge_core.services.ingestion_pipeline import ingest_document


class Command(BaseCommand):
    help = "Ingest knowledge documents into the Knowledge Core (Pinecone)."

    def add_arguments(self, parser):
        parser.add_argument("--all-pending", action="store_true", dest="all_pending")
        parser.add_argument("--all-failed", action="store_true", dest="all_failed")
        parser.add_argument("--document-id", type=str, dest="document_id", default=None)
        parser.add_argument("--dry-run", action="store_true", dest="dry_run")

    def handle(self, *args, **opts):
        dry_run = opts["dry_run"]

        if opts["document_id"]:
            try:
                docs = [KnowledgeDocument.objects.get(pk=opts["document_id"])]
            except KnowledgeDocument.DoesNotExist as exc:
                raise CommandError(f"No document with id {opts['document_id']}") from exc
        elif opts["all_pending"]:
            docs = list(KnowledgeDocument.objects.filter(ingestion_status=IngestionStatus.PENDING))
        elif opts["all_failed"]:
            docs = list(KnowledgeDocument.objects.filter(ingestion_status=IngestionStatus.FAILED))
        else:
            docs = list(
                KnowledgeDocument.objects.filter(
                    ingestion_status__in=[IngestionStatus.PENDING, IngestionStatus.FAILED]
                )
            )

        if not docs:
            self.stdout.write(self.style.WARNING("No documents to ingest."))
            return

        self.stdout.write(f"Ingesting {len(docs)} document(s){' (dry-run)' if dry_run else ''}…")
        ok = 0
        for doc in docs:
            result = ingest_document(doc, dry_run=dry_run)
            if result.ok:
                ok += 1
                self.stdout.write(
                    self.style.SUCCESS(f"  ✓ {doc.title} — {result.chunk_count} chunks")
                )
            else:
                self.stdout.write(self.style.ERROR(f"  ✗ {doc.title} — {result.error}"))

        self.stdout.write(self.style.SUCCESS(f"Done: {ok}/{len(docs)} succeeded."))
