"""Rebuild/reconcile Pinecone namespaces from authoritative relational state.

``--all`` reconciles every namespace the application can know about: current and
historical KnowledgeDocument rows, canonical application namespaces, and namespaces
reported by the configured Pinecone index. Remote-only stale namespaces are therefore
cleared even when there are zero current relational documents to re-ingest.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.knowledge_core.services.ingestion_pipeline import reingest_namespace
from apps.knowledge_core.services.namespace_router import CANONICAL_NAMESPACES, normalize_namespace
from apps.knowledge_core.services.pinecone_upserter import PineconeUpserter, PineconeUpsertError


class Command(BaseCommand):
    help = "Reconcile one or all Knowledge namespaces against current relational sources."

    def add_arguments(self, parser):
        parser.add_argument("--namespace", type=str, default="", dest="namespace")
        parser.add_argument("--all", action="store_true", dest="all_namespaces")
        parser.add_argument("--dry-run", action="store_true", dest="dry_run")

    def handle(self, *args, **opts):
        from apps.knowledge_core.models import KnowledgeDocument

        namespace = (opts["namespace"] or "").strip()
        dry_run = bool(opts["dry_run"])
        all_namespaces = bool(opts["all_namespaces"])
        if bool(namespace) == all_namespaces:
            raise CommandError("Choose exactly one of --namespace <name> or --all")

        upserter = PineconeUpserter()
        remote_before: dict[str, int] = {}

        if all_namespaces:
            # A non-dry-run all-namespace reconciliation must be able to inventory the
            # configured remote index. Otherwise remote-only stale namespaces cannot be
            # discovered and reporting success would be false.
            if not dry_run and not upserter.enabled:
                raise CommandError(
                    "Remote Pinecone inventory is unavailable. Configure the application "
                    "for the intended non-production/production index before running --all."
                )
            try:
                remote_before = upserter.namespace_counts() if upserter.enabled else {}
            except PineconeUpsertError as exc:
                raise CommandError(str(exc)) from exc

            db_namespaces = {
                normalize_namespace(value)
                for value in KnowledgeDocument.objects.exclude(namespace="").values_list(
                    "namespace", flat=True
                )
                if value
            }
            namespaces = sorted(
                db_namespaces
                | {normalize_namespace(value) for value in CANONICAL_NAMESPACES}
                | {normalize_namespace(value) for value in remote_before}
            )
        else:
            namespaces = [normalize_namespace(namespace)]
            if upserter.enabled:
                try:
                    remote_before = upserter.namespace_counts()
                except PineconeUpsertError as exc:
                    raise CommandError(str(exc)) from exc

        rows: list[dict] = []
        total_reingested = 0
        total_current_docs = 0

        for ns in namespaces:
            current_docs = KnowledgeDocument.objects.filter(
                namespace=ns, is_current=True
            ).count()
            total_current_docs += current_docs
            before = remote_before.get(ns, 0) if upserter.enabled else None

            results = reingest_namespace(ns, dry_run=dry_run)
            failed = [result for result in results if not result.ok]
            reingested = sum(1 for result in results if result.ok)
            total_reingested += reingested
            rows.append(
                {
                    "namespace": ns,
                    "before": before,
                    "current_docs": current_docs,
                    "cleared": not dry_run,
                    "reingested": reingested,
                    "failed": failed,
                }
            )

        remote_after: dict[str, int] = {}
        if upserter.enabled and not dry_run:
            try:
                remote_after = upserter.namespace_counts()
            except PineconeUpsertError as exc:
                raise CommandError(
                    f"Reconciliation ran, but remote-after inventory failed: {exc}"
                ) from exc

        failures = 0
        for row in rows:
            failures += len(row["failed"])
            before = "n/a" if row["before"] is None else str(row["before"])
            after = (
                "dry-run"
                if dry_run
                else (str(remote_after.get(row["namespace"], 0)) if upserter.enabled else "n/a")
            )
            status = "FAIL" if row["failed"] else ("DRY-RUN" if dry_run else "OK")
            self.stdout.write(
                "NAMESPACE={namespace} REMOTE_BEFORE={before} CURRENT_DOCS={current_docs} "
                "DELETED/CLEARED={cleared} REINGESTED={reingested} REMOTE_AFTER={after} "
                "STATUS={status}".format(
                    namespace=row["namespace"],
                    before=before,
                    current_docs=row["current_docs"],
                    cleared="NO (dry-run)" if dry_run else "YES",
                    reingested=row["reingested"],
                    after=after,
                    status=status,
                )
            )
            for result in row["failed"]:
                self.stdout.write(
                    self.style.ERROR(
                        f"  failed document={result.document.id} title={result.document.title}"
                    )
                )

        self.stdout.write(
            "TOTALS namespaces={namespaces} current_docs={docs} reingested={reingested} "
            "failures={failures}".format(
                namespaces=len(rows),
                docs=total_current_docs,
                reingested=total_reingested,
                failures=failures,
            )
        )
        if failures:
            raise CommandError(f"{failures} document(s) failed during namespace reconciliation")
