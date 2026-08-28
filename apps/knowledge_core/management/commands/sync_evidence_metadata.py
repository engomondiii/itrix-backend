"""Synchronize governance metadata for the small set of evidentiary Knowledge sources.

This command does not create facts from filenames and does not change disclosure tiers.  It
only binds evidence sources already present in the governed corpus to the method family and
source-status language supported by the authoritative project materials.  Re-ingestion is
required after a metadata change so vector metadata remains identical to the database.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.knowledge_core.models import KnowledgeDocument


EVIDENCE_METADATA: dict[str, dict[str, str]] = {
    "knowledge_docs/controlled_public/FQNM_arXiv.pdf": {
        "technology_family": "fqnm",
        "source_authority": "working",
        "canonical_rule": "Published as an arXiv preprint; do not describe it as peer-reviewed evidence.",
    },
    "knowledge_docs/nda_only/Master_Thesis_2026_Feb.pdf": {
        "technology_family": "cre",
        "source_authority": "working",
        "canonical_rule": "Master's thesis evidence for AXIOM-CRE; do not generalize it into universal workload proof.",
    },
    "knowledge_docs/nda_only/TurboQuant_vs_FQNM_Comparison_Paper_V1.0.docx": {
        "technology_family": "fqnm",
        "source_authority": "working",
        "canonical_rule": "Restricted comparison evidence; claims remain bounded by the source and its disclosure authorization.",
    },
}


class Command(BaseCommand):
    help = "Synchronize method-family/source-status metadata for governed evidence documents."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", dest="dry_run")

    def handle(self, *args, **opts):
        dry_run = bool(opts["dry_run"])
        changed = unchanged = missing = 0

        for file_path, desired in EVIDENCE_METADATA.items():
            try:
                doc = KnowledgeDocument.objects.get(file_path=file_path, is_current=True)
            except KnowledgeDocument.DoesNotExist:
                missing += 1
                self.stdout.write(self.style.ERROR(f"  ! missing current evidence source: {file_path}"))
                continue

            updates: list[str] = []
            for field, value in desired.items():
                if getattr(doc, field) != value:
                    setattr(doc, field, value)
                    updates.append(field)

            if not updates:
                unchanged += 1
                self.stdout.write(f"  = current: {file_path}")
                continue

            changed += 1
            if dry_run:
                self.stdout.write(self.style.WARNING(f"  would update {file_path}: {', '.join(updates)}"))
                continue

            doc.ingestion_status = "PENDING"
            doc.save(update_fields=updates + ["ingestion_status", "updated_at"])
            self.stdout.write(self.style.SUCCESS(f"  ~ updated {file_path}: {', '.join(updates)}"))

        if missing:
            raise RuntimeError(f"Evidence synchronization failed: {missing} required source(s) missing/currentness-invalid.")

        verb = "Would update" if dry_run else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{verb} {changed}; {unchanged} already synchronized; {missing} missing."))
        if changed and not dry_run:
            self.stdout.write("Re-ingest affected namespaces (or use reingest_namespace --all) before release.")
