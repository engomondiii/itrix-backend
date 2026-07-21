"""
``python manage.py register_knowledge_docs``

Walks the ``knowledge_docs/`` tree and registers a ``KnowledgeDocument`` for every
ingestible file (``.docx`` / ``.pdf`` / ``.txt`` / ``.md``), inferring:

* **disclosure_level** from the folder name (public / controlled_public / nda_only /
  internal_only), and
* **namespace** from filename patterns (technology / proofs / alpha-compute / alpha-core /
  licensing / company / general).

Idempotent: keyed on ``file_path`` via get_or_create, so re-running won't duplicate. Use
``--dry-run`` to preview the mapping without writing, and ``--base`` to point at a different
knowledge_docs directory.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand

from apps.knowledge_core.models import KnowledgeDocument

INGESTIBLE_EXTS = {".docx", ".pdf", ".txt", ".md", ".markdown"}

# Folder name -> disclosure level (matches the five-tier model).
FOLDER_DISCLOSURE = {
    "public": "public",
    "controlled_public": "controlled_public",
    "nda_only": "nda_only",
    # ── v6.0 Phase 2: the sixth tier ─────────────────────────────────────────
    # Scoped PER CUSTOMER and never cross-served. The folder decides the tier; the
    # per-customer scope is applied separately by the disclosure filter.
    "customer_contract": "customer_contract",
    "internal_only": "internal_only",
}

# ── THE ATTACHMENT STORE IS NEVER A KNOWLEDGE SOURCE (§8.2) ──────────────────
# Visitor attachments are session-scoped context for the thread that owns them. They are
# not embedded into the shared index, not indexed, and not cross-served. This command
# walks knowledge_docs/ ONLY, and the assertion below makes that explicit so a future
# refactor pointing it at a different root fails loudly rather than silently publishing
# every upload a visitor ever made.
FORBIDDEN_ROOTS = ("private_blobs", "attachments", "media")


def assert_not_attachment_store(base) -> None:
    """Refuse to register documents from anywhere that could hold visitor uploads."""
    resolved = str(base.resolve()).lower()
    for forbidden in FORBIDDEN_ROOTS:
        if f"/{forbidden}" in resolved or resolved.endswith(forbidden):
            raise RuntimeError(
                f"Refusing to register knowledge documents from {base!r}: the attachment "
                f"store is never a Knowledge Core source (Backend v6.0 §8.2)."
            )


def namespace_for(filename: str) -> str:
    """Infer a canonical namespace from the filename (case-insensitive)."""
    n = filename.lower()

    # Proof / research materials.
    if "arxiv" in n or "thesis" in n or "comparison" in n or "turboquant" in n:
        return "proofs"
    # Core technology overviews (the triad + unified view).
    if "axiom" in n or "cre_overview" in n or "fqnm_overview" in n or "unified mathematical" in n:
        return "technology"
    # ALPHA Core product.
    if "alpha core" in n or "alpha_core" in n:
        return "alpha-core"
    # ALPHA Compute product + workload/bottleneck materials + the compute white paper.
    if (
        "alpha_compute" in n
        or "alpha compute" in n
        or "computational workload" in n
        or "bottleneck materials" in n
    ):
        return "alpha-compute"
    # Pricing / licensing.
    if "pricing" in n or "licens" in n:
        return "licensing"
    # Company / brand / investor / project-direction materials.
    if (
        "brand story" in n
        or "kickoff" in n
        or "investor" in n
        or "playbook" in n
        or "theme system" in n
        or "architecture flow" in n
        or "operations command" in n
        or "milestone" in n
    ):
        return "company"
    # Everything else (website build / specs / wireframes / personas / journey / templates).
    return "general"


def title_for(path: Path) -> str:
    stem = path.stem
    # Tidy common noise in the filenames.
    for junk in (" (1)", " (2)", "_V2.0", "_v2.0", "_V1.0", "_v1.0", "_V2", "_v2"):
        stem = stem.replace(junk, "")
    return stem.replace("_", " ").strip()


class Command(BaseCommand):
    help = "Register knowledge_docs files as KnowledgeDocument records."

    def add_arguments(self, parser):
        parser.add_argument("--base", type=str, default="knowledge_docs")
        parser.add_argument("--dry-run", action="store_true", dest="dry_run")

    def handle(self, *args, **opts):
        base = Path(opts["base"])
        dry_run = opts["dry_run"]

        if not base.exists():
            self.stdout.write(self.style.ERROR(f"Directory not found: {base.resolve()}"))
            return

        created = existing = skipped = 0
        for folder, disclosure in FOLDER_DISCLOSURE.items():
            d = base / folder
            if not d.exists():
                continue
            for f in sorted(d.iterdir()):
                if not f.is_file():
                    continue
                if f.suffix.lower() not in INGESTIBLE_EXTS:
                    skipped += 1
                    self.stdout.write(self.style.WARNING(f"  skip (unsupported): {folder}/{f.name}"))
                    continue

                ns = namespace_for(f.name)
                title = title_for(f)

                if dry_run:
                    self.stdout.write(f"  would register [{disclosure:17}] [{ns:13}] {title}")
                    created += 1
                    continue

                obj, made = KnowledgeDocument.objects.get_or_create(
                    file_path=str(f),
                    defaults={
                        "title": title,
                        "namespace": ns,
                        "disclosure_level": disclosure,
                    },
                )
                if made:
                    created += 1
                    self.stdout.write(self.style.SUCCESS(f"  + [{disclosure:17}] [{ns:13}] {title}"))
                else:
                    existing += 1
                    self.stdout.write(f"  = exists: {title}")

        verb = "Would register" if dry_run else "Registered"
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{verb} {created} document(s); {existing} already present; {skipped} skipped."
            )
        )
        if not dry_run:
            self.stdout.write("Next: python manage.py ingest_documents")
