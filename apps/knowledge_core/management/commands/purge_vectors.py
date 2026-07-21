"""
``python manage.py purge_vectors``

Retract vectors for changed or removed documents (Backend v6.0 §Phase 1).

── WHY THIS EXISTS ──────────────────────────────────────────────────────────
THE FOLDER IS THE ACCESS-CONTROL DECISION. Moving a document from ``public/`` to
``internal_only/`` changes what the retriever is ALLOWED to return — but it does not
remove the vectors already sitting in the index under the old tier. Until they are
purged, the old chunks remain retrievable at the old ceiling.

Re-tiering therefore REQUIRES a vector purge before re-ingest. That is the whole reason
this command is in Phase 1 rather than being deferred: it is the second half of the
re-tier operation, and a re-tier without it is a disclosure incident with a paper trail
that says it was handled.

    manage.py purge_vectors --document <id>       one document
    manage.py purge_vectors --namespace technology
    manage.py purge_vectors --missing             docs whose file no longer exists
    manage.py purge_vectors --all                 everything (full rebuild)
    manage.py purge_vectors --dry-run             report only
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.knowledge_core.models import KnowledgeDocument


class Command(BaseCommand):
    help = "Retract Pinecone vectors for changed, re-tiered or removed documents."

    def add_arguments(self, parser):
        parser.add_argument("--document", help="Purge one document by id.")
        parser.add_argument("--namespace", help="Purge an entire namespace.")
        parser.add_argument(
            "--missing",
            action="store_true",
            help="Purge documents whose source file no longer exists on disk.",
        )
        parser.add_argument("--all", action="store_true", help="Purge everything.")
        parser.add_argument("--dry-run", action="store_true", help="Report without deleting.")
        parser.add_argument(
            "--yes", action="store_true", help="Skip the confirmation prompt for --all."
        )

    def handle(self, *args, **options):
        targets = self._targets(options)
        if targets is None:
            raise CommandError(
                "Choose one of --document, --namespace, --missing or --all."
            )

        docs = list(targets)
        if not docs:
            self.stdout.write(self.style.SUCCESS("Nothing to purge."))
            return

        self.stdout.write(f"{len(docs)} document(s) selected:")
        for doc in docs[:25]:
            self.stdout.write(
                f"  {doc.id}  [{doc.disclosure_level:<18}] {doc.namespace:<14} {doc.title[:50]}"
            )
        if len(docs) > 25:
            self.stdout.write(f"  ... and {len(docs) - 25} more")

        if options["dry_run"]:
            self.stdout.write(self.style.NOTICE("Dry run — nothing deleted."))
            return

        if options["all"] and not options["yes"]:
            self.stdout.write(
                self.style.WARNING(
                    "Refusing to purge the whole index without --yes. "
                    "A full purge means every agent degrades to its deterministic "
                    "fallback until re-ingest completes."
                )
            )
            return

        purged, failed = self._purge(docs)
        self.stdout.write(
            self.style.SUCCESS(f"Purged {purged} document(s). {failed} failure(s).")
        )
        self.stdout.write(
            self.style.NOTICE(
                "Re-ingest now:  manage.py register_knowledge_docs && "
                "manage.py reingest_namespace --all"
            )
        )

    def _targets(self, options):
        if options["document"]:
            return KnowledgeDocument.objects.filter(id=options["document"])
        if options["namespace"]:
            return KnowledgeDocument.objects.filter(namespace=options["namespace"])
        if options["missing"]:
            return [doc for doc in KnowledgeDocument.objects.all() if self._is_missing(doc)]
        if options["all"]:
            return KnowledgeDocument.objects.all()
        return None

    @staticmethod
    def _is_missing(doc) -> bool:
        raw = getattr(doc, "file_path", "") or ""
        if not raw:
            return True
        path = Path(raw)
        if not path.is_absolute():
            path = Path(settings.BASE_DIR) / raw
        return not path.exists()

    def _purge(self, docs) -> tuple[int, int]:
        purged = failed = 0
        index = self._index()

        for doc in docs:
            try:
                chunk_ids = self._chunk_ids(doc)
                if index is not None and chunk_ids:
                    index.delete(ids=chunk_ids, namespace=doc.namespace)
                self._mark_retracted(doc)
                purged += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                self.stderr.write(self.style.ERROR(f"  {doc.id}: {exc}"))
        return purged, failed

    def _index(self):
        """
        The Pinecone index handle, or None when the engine is off.

        Returning None rather than raising lets a purge run in a local/test environment:
        the DB-side retraction still happens, so the document is correctly marked and a
        later re-ingest is consistent.
        """
        try:
            from apps.ai_engine.services.pinecone_client import get_index

            return get_index()
        except Exception:  # noqa: BLE001
            self.stdout.write(
                self.style.WARNING("Pinecone unavailable — retracting locally only.")
            )
            return None

    @staticmethod
    def _chunk_ids(doc) -> list[str]:
        try:
            from apps.knowledge_core.models import KnowledgeChunk

            return [
                str(cid)
                for cid in KnowledgeChunk.objects.filter(document=doc).values_list(
                    "chunk_id", flat=True
                )
                if cid
            ]
        except Exception:  # noqa: BLE001
            return []

    @staticmethod
    def _mark_retracted(doc) -> None:
        """Mark the document un-ingested so a re-ingest knows it must run again."""
        updates = []
        for field, value in (("is_ingested", False), ("chunk_count", 0)):
            if hasattr(doc, field):
                setattr(doc, field, value)
                updates.append(field)
        if updates:
            doc.save(update_fields=updates)

        try:
            from apps.knowledge_core.models import KnowledgeChunk

            KnowledgeChunk.objects.filter(document=doc).delete()
        except Exception:  # noqa: BLE001
            pass
