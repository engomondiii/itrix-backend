"""Rebuild the shared itriX knowledge corpus deterministically.

This command intentionally touches ONLY KnowledgeDocument/KnowledgeChunk/Pinecone state.
It does not touch leads, threads, journey state, email capture, personalised pages, visitor
attachments, or any conversation-state service.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from apps.knowledge_core.management.commands.register_knowledge_docs import (
    FOLDER_DISCLOSURE,
    INGESTIBLE_EXTS,
    SUPERSEDED_FILENAMES,
)
from apps.knowledge_core.models import IngestionStatus, KnowledgeChunk, KnowledgeDocument
from apps.knowledge_core.services.ingestion_pipeline import ingest_document
from apps.knowledge_core.services.namespace_router import CANONICAL_NAMESPACES
from apps.knowledge_core.services.pinecone_upserter import PineconeUpserter


class Command(BaseCommand):
    help = "Reconcile, purge and fully rebuild the itriX Knowledge Core in Pinecone."

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Required acknowledgement: this clears and rebuilds the shared Pinecone namespaces.",
        )
        parser.add_argument("--base", default="knowledge_docs")

    def handle(self, *args, **opts):
        if not opts["yes"]:
            raise CommandError("Refusing full knowledge rebuild without --yes")

        base = Path(opts["base"])
        if not base.is_absolute():
            base = Path(settings.BASE_DIR) / base
        if not base.exists():
            raise CommandError(f"Knowledge directory not found: {base}")

        self.stdout.write(self.style.MIGRATE_HEADING("1. Register/reconcile source documents"))
        call_command("register_knowledge_docs", base=str(base))

        current_paths = self._current_paths(base)
        duplicates = self._deduplicate_logical_paths(current_paths)
        if duplicates:
            self.stdout.write(
                self.style.WARNING(
                    f"Removed {duplicates} duplicate KnowledgeDocument row(s) caused by path-format drift."
                )
            )
        removed = self._remove_stale_rows(current_paths)
        if removed:
            self.stdout.write(self.style.WARNING(f"Removed {removed} superseded/missing KnowledgeDocument row(s)."))

        # Re-apply source-folder policy to all current file-backed rows. Registration
        # already does this, but this makes the rebuild self-contained and auditable.
        publicised = self._reconcile_disclosure(base)
        self.stdout.write(f"Public knowledge rows reconciled: {publicised}")

        docs = list(KnowledgeDocument.objects.all().order_by("file_path", "created_at"))
        if not docs:
            raise CommandError("No KnowledgeDocument rows to ingest after reconciliation.")

        self.stdout.write(self.style.MIGRATE_HEADING("2. Clear remote namespaces"))
        upserter = PineconeUpserter()
        namespaces = sorted(CANONICAL_NAMESPACES | {d.namespace for d in docs if d.namespace})
        for ns in namespaces:
            if not upserter.delete_namespace(ns):
                raise CommandError(f"Could not clear Pinecone namespace {ns!r}")
            self.stdout.write(f"  cleared: {ns}")

        self.stdout.write(self.style.MIGRATE_HEADING("3. Reset local chunk state"))
        KnowledgeChunk.objects.all().delete()
        KnowledgeDocument.objects.update(
            ingestion_status=IngestionStatus.PENDING,
            ingestion_error="",
            chunk_count=0,
            content_hash="",
            last_ingested_at=None,
        )

        self.stdout.write(self.style.MIGRATE_HEADING("4. Re-embed and re-ingest"))
        ok = 0
        for doc in KnowledgeDocument.objects.all().order_by("file_path", "created_at"):
            result = ingest_document(doc)
            if not result.ok:
                raise CommandError(f"Ingestion failed for {doc.title}: {result.error}")
            ok += 1
            self.stdout.write(
                self.style.SUCCESS(
                    f"  ✓ [{doc.disclosure_level:<17}] [{doc.namespace:<13}] {doc.title} — {result.chunk_count} chunks"
                )
            )

        self.stdout.write(self.style.MIGRATE_HEADING("5. Validate"))
        call_command("validate_knowledge_core")
        self.stdout.write(self.style.SUCCESS(f"Knowledge rebuild complete: {ok} document(s)."))


    @staticmethod
    def _deduplicate_logical_paths(current_paths: set[str]) -> int:
        """Collapse Windows/Linux path variants before a full rebuild.

        Older registrations could store ``knowledge_docs\\...`` on Windows and
        ``knowledge_docs/...`` on Linux as different rows.  A full rebuild must not
        re-embed both logical copies.  Prefer the canonical POSIX row when it exists;
        otherwise keep the oldest row and normalize its path.
        """
        groups: dict[str, list[KnowledgeDocument]] = {}
        for doc in KnowledgeDocument.objects.exclude(file_path="").order_by("created_at"):
            raw = (doc.file_path or "").replace("\\", "/")
            if raw in current_paths:
                groups.setdefault(raw, []).append(doc)

        removed = 0
        for canonical, docs in groups.items():
            if not docs:
                continue
            survivor = next((d for d in docs if d.file_path == canonical), docs[0])
            if survivor.file_path != canonical:
                survivor.file_path = canonical
                survivor.save(update_fields=["file_path", "updated_at"])
            duplicate_ids = [d.id for d in docs if d.id != survivor.id]
            if duplicate_ids:
                removed += len(duplicate_ids)
                KnowledgeDocument.objects.filter(id__in=duplicate_ids).delete()
        return removed

    @staticmethod
    def _current_paths(base: Path) -> set[str]:
        repo = Path(settings.BASE_DIR)
        out: set[str] = set()
        for folder in FOLDER_DISCLOSURE:
            directory = base / folder
            if not directory.exists():
                continue
            for path in directory.iterdir():
                if (
                    path.is_file()
                    and path.suffix.lower() in INGESTIBLE_EXTS
                    and path.name not in SUPERSEDED_FILENAMES
                ):
                    try:
                        rel = path.relative_to(repo)
                    except ValueError:
                        rel = path
                    out.add(rel.as_posix())
        return out

    @staticmethod
    def _remove_stale_rows(current_paths: set[str]) -> int:
        stale_ids = []
        for doc in KnowledgeDocument.objects.exclude(file_path=""):
            raw = (doc.file_path or "").replace("\\", "/")
            if raw.startswith("knowledge_docs/") and raw not in current_paths:
                stale_ids.append(doc.id)
        if not stale_ids:
            return 0
        count = len(stale_ids)
        KnowledgeDocument.objects.filter(id__in=stale_ids).delete()
        return count

    @staticmethod
    def _reconcile_disclosure(base: Path) -> int:
        repo = Path(settings.BASE_DIR)
        changed = 0
        for folder, level in FOLDER_DISCLOSURE.items():
            directory = base / folder
            if not directory.exists():
                continue
            for path in directory.iterdir():
                if (
                    not path.is_file()
                    or path.suffix.lower() not in INGESTIBLE_EXTS
                    or path.name in SUPERSEDED_FILENAMES
                ):
                    continue
                try:
                    rel = path.relative_to(repo).as_posix()
                except ValueError:
                    rel = path.as_posix()
                updated = KnowledgeDocument.objects.filter(file_path=rel).exclude(
                    disclosure_level=level
                ).update(disclosure_level=level, ingestion_status=IngestionStatus.PENDING)
                changed += updated
        return changed
