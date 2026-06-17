"""
``python manage.py validate_knowledge_core``

Health-checks the Knowledge Core configuration and data, without mutating anything:

* configuration: whether the AI engine / Pinecone are enabled and keys are present
* documents: counts by ingestion status; lists FAILED docs and their errors
* documents missing a source (no file_path and no uploaded_file)
* documents that are COMPLETE but have zero chunks (suspect)
* namespace summary (documents + chunks per namespace)

Exits non-zero if problems are found (handy in CI / pre-deploy).
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Count

from apps.knowledge_core.models import IngestionStatus, KnowledgeChunk, KnowledgeDocument


class Command(BaseCommand):
    help = "Validate Knowledge Core configuration and ingested data."

    def handle(self, *args, **opts):
        problems = 0

        # ── Configuration ────────────────────────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING("Configuration"))
        self.stdout.write(f"  ENABLE_AI_ENGINE      : {settings.ENABLE_AI_ENGINE}")
        self.stdout.write(f"  OPENAI key present    : {bool(settings.OPENAI_API_KEY)}")
        self.stdout.write(f"  PINECONE key present  : {bool(settings.PINECONE_API_KEY)}")
        self.stdout.write(f"  PINECONE_INDEX        : {settings.PINECONE_INDEX}")
        self.stdout.write(f"  EMBEDDING model       : {settings.OPENAI_EMBEDDING_MODEL}")
        if settings.ENABLE_AI_ENGINE and not (settings.OPENAI_API_KEY and settings.PINECONE_API_KEY):
            self.stdout.write(self.style.ERROR("  ! AI engine enabled but OpenAI/Pinecone keys missing."))
            problems += 1

        # ── Document status counts ───────────────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING("Documents"))
        total = KnowledgeDocument.objects.count()
        self.stdout.write(f"  total: {total}")
        for s in IngestionStatus:
            n = KnowledgeDocument.objects.filter(ingestion_status=s).count()
            self.stdout.write(f"    {s.value:<10}: {n}")

        # ── Failed documents ─────────────────────────────────────────────────
        failed = KnowledgeDocument.objects.filter(ingestion_status=IngestionStatus.FAILED)
        if failed.exists():
            problems += failed.count()
            self.stdout.write(self.style.ERROR(f"  {failed.count()} FAILED document(s):"))
            for doc in failed:
                self.stdout.write(self.style.ERROR(f"    - {doc.title}: {doc.ingestion_error[:120]}"))

        # ── Missing source ───────────────────────────────────────────────────
        missing_source = [
            d for d in KnowledgeDocument.objects.all() if not d.source_ref
        ]
        if missing_source:
            problems += len(missing_source)
            self.stdout.write(self.style.ERROR(f"  {len(missing_source)} document(s) with no source:"))
            for doc in missing_source:
                self.stdout.write(self.style.ERROR(f"    - {doc.title}"))

        # ── Complete-but-empty ───────────────────────────────────────────────
        empty_complete = KnowledgeDocument.objects.filter(
            ingestion_status=IngestionStatus.COMPLETE, chunk_count=0
        )
        if empty_complete.exists():
            problems += empty_complete.count()
            self.stdout.write(
                self.style.WARNING(f"  {empty_complete.count()} COMPLETE document(s) with 0 chunks.")
            )

        # ── Namespace summary ────────────────────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING("Namespaces"))
        ns_docs = {
            r["namespace"]: r["n"]
            for r in KnowledgeDocument.objects.values("namespace").annotate(n=Count("id"))
        }
        ns_chunks = {
            r["namespace"]: r["n"]
            for r in KnowledgeChunk.objects.values("namespace").annotate(n=Count("id"))
        }
        for ns in sorted(set(ns_docs) | set(ns_chunks)):
            self.stdout.write(f"  {ns:<18} docs={ns_docs.get(ns, 0):<4} chunks={ns_chunks.get(ns, 0)}")

        # ── Verdict ──────────────────────────────────────────────────────────
        if problems:
            self.stdout.write(self.style.ERROR(f"\nValidation finished with {problems} problem(s)."))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS("\nKnowledge Core validation passed."))
