"""
``python manage.py reingest_namespace --namespace <name>``

Clears a Pinecone namespace and re-ingests every document registered under it. Useful
after changing the chunker, the embedding model, or document contents.

Options:
    --namespace <name>   one namespace to rebuild
    --all                rebuild every namespace containing a current document
    --dry-run            parse + chunk only; no embed/upsert/persist
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.knowledge_core.services.ingestion_pipeline import reingest_namespace


class Command(BaseCommand):
    help = "Re-ingest all documents in a namespace (clears the namespace first)."

    def add_arguments(self, parser):
        parser.add_argument("--namespace", type=str, default="", dest="namespace")
        parser.add_argument("--all", action="store_true", dest="all_namespaces")
        parser.add_argument("--dry-run", action="store_true", dest="dry_run")

    def handle(self, *args, **opts):
        namespace = opts["namespace"]
        dry_run = opts["dry_run"]
        all_namespaces = bool(opts["all_namespaces"])
        if bool(namespace) == all_namespaces:
            raise CommandError("Choose exactly one of --namespace <name> or --all")
        if all_namespaces:
            from apps.knowledge_core.models import KnowledgeDocument
            namespaces = list(
                KnowledgeDocument.objects.filter(is_current=True)
                .exclude(namespace="")
                .values_list("namespace", flat=True)
                .distinct()
                .order_by("namespace")
            )
        else:
            namespaces = [namespace]

        total_ok = total = 0
        for ns in namespaces:
            self.stdout.write(f"Re-ingesting namespace '{ns}'{' (dry-run)' if dry_run else ''}…")
            results = reingest_namespace(ns, dry_run=dry_run)
            if not results:
                self.stdout.write(self.style.WARNING(f"No current documents found in namespace '{ns}'."))
                continue
            for result in results:
                total += 1
                if result.ok:
                    total_ok += 1
                    self.stdout.write(self.style.SUCCESS(f"  ✓ {result.document.title} — {result.chunk_count} chunks"))
                else:
                    self.stdout.write(self.style.ERROR(f"  ✗ {result.document.title} — {result.error}"))
        self.stdout.write(self.style.SUCCESS(f"Done: {total_ok}/{total} succeeded."))
        if total_ok != total:
            raise CommandError(f"{total-total_ok} document(s) failed during re-ingestion")
