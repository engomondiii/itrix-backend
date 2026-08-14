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
from apps.knowledge_core.services.namespace_router import CANONICAL_NAMESPACES


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

        # ── Current product doctrine ─────────────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING("Canonical product source"))
        canonical = KnowledgeDocument.objects.filter(
            title__icontains="WP ALPHA Compute Core v2.4",
            ingestion_status=IngestionStatus.COMPLETE,
            disclosure_level="public",
        )
        if not canonical.exists():
            # title_for preserves punctuation slightly differently across export names;
            # fall back to the file path, which is deterministic in this repo.
            canonical = KnowledgeDocument.objects.filter(
                file_path__icontains="WP_ALPHA_Compute_Core_v2.4",
                ingestion_status=IngestionStatus.COMPLETE,
                disclosure_level="public",
            )
        if canonical.exists():
            doc = canonical.first()
            self.stdout.write(self.style.SUCCESS(f"  current: {doc.title} ({doc.chunk_count} chunks)"))
        else:
            self.stdout.write(self.style.ERROR("  ! Current ALPHA Compute/Core v2.4 source is not COMPLETE + public."))
            problems += 1

        # Product/research source folders are visitor-readable by policy. Operational
        # internal_only and customer_contract are intentionally exempt.
        non_public_product_sources = KnowledgeDocument.objects.filter(
            file_path__regex=r"^knowledge_docs/(public|controlled_public|nda_only)/",
        ).exclude(disclosure_level="public")
        if non_public_product_sources.exists():
            problems += non_public_product_sources.count()
            self.stdout.write(self.style.ERROR(
                f"  ! {non_public_product_sources.count()} product/research source(s) are not public."
            ))

        # ── Live Pinecone parity ──────────────────────────────────────────────
        if settings.ENABLE_AI_ENGINE and settings.PINECONE_API_KEY:
            self.stdout.write(self.style.MIGRATE_HEADING("Pinecone parity"))
            try:
                from pinecone import Pinecone

                stats = Pinecone(api_key=settings.PINECONE_API_KEY).Index(
                    settings.PINECONE_INDEX
                ).describe_index_stats()
                remote_obj = getattr(stats, "namespaces", {}) or {}
                remote = {}
                for ns, summary in remote_obj.items():
                    remote[ns] = int(
                        getattr(summary, "vector_count", 0)
                        if not isinstance(summary, dict)
                        else summary.get("vector_count", 0)
                    )
                all_ns = sorted(set(ns_chunks) | set(remote) | CANONICAL_NAMESPACES)
                for ns in all_ns:
                    local_n = int(ns_chunks.get(ns, 0))
                    remote_n = int(remote.get(ns, 0))
                    marker = "OK" if local_n == remote_n else "MISMATCH"
                    self.stdout.write(f"  {ns:<18} db={local_n:<5} pinecone={remote_n:<5} {marker}")
                    if local_n != remote_n:
                        problems += 1
            except Exception as exc:  # noqa: BLE001
                problems += 1
                self.stdout.write(self.style.ERROR(f"  ! Pinecone parity check failed: {exc}"))

        # ── Verdict ──────────────────────────────────────────────────────────
        if problems:
            self.stdout.write(self.style.ERROR(f"\nValidation finished with {problems} problem(s)."))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS("\nKnowledge Core validation passed."))
