"""
``python manage.py reingest_namespace --namespace <name>``

Clears a Pinecone namespace and re-ingests every document registered under it. Useful
after changing the chunker, the embedding model, or document contents.

Options:
    --namespace <name>   (required) the namespace to rebuild
    --dry-run            parse + chunk only; no embed/upsert/persist
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.knowledge_core.services.ingestion_pipeline import reingest_namespace


class Command(BaseCommand):
    help = "Re-ingest all documents in a namespace (clears the namespace first)."

    def add_arguments(self, parser):
        parser.add_argument("--namespace", type=str, required=True, dest="namespace")
        parser.add_argument("--dry-run", action="store_true", dest="dry_run")

    def handle(self, *args, **opts):
        namespace = opts["namespace"]
        dry_run = opts["dry_run"]
        if not namespace:
            raise CommandError("--namespace is required")

        self.stdout.write(
            f"Re-ingesting namespace '{namespace}'{' (dry-run)' if dry_run else ''}…"
        )
        results = reingest_namespace(namespace, dry_run=dry_run)

        if not results:
            self.stdout.write(self.style.WARNING(f"No documents found in namespace '{namespace}'."))
            return

        ok = 0
        for result in results:
            if result.ok:
                ok += 1
                self.stdout.write(
                    self.style.SUCCESS(f"  ✓ {result.document.title} — {result.chunk_count} chunks")
                )
            else:
                self.stdout.write(self.style.ERROR(f"  ✗ {result.document.title} — {result.error}"))

        self.stdout.write(self.style.SUCCESS(f"Done: {ok}/{len(results)} succeeded."))
