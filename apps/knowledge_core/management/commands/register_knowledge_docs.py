"""
``python manage.py register_knowledge_docs``

Walks the ``knowledge_docs/`` tree and registers a ``KnowledgeDocument`` for every
ingestible file (``.docx`` / ``.pdf`` / ``.txt`` / ``.md``), inferring:

* **disclosure_level** using the visitor-knowledge policy: product/research source folders
  (public / controlled_public / nda_only) are PUBLIC by default; internal_only and
  customer_contract remain non-public, and
* **namespace** from filename patterns (technology / proofs / alpha-compute / alpha-core /
  licensing / company / general).

Idempotent: keyed on the POSIX form of ``file_path``, so re-running won't duplicate —
including across operating systems. Use
``--dry-run`` to preview the mapping without writing, and ``--base`` to point at a different
knowledge_docs directory.
"""

from __future__ import annotations

from pathlib import Path
import re

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.knowledge_core.models import KnowledgeDocument

INGESTIBLE_EXTS = {".docx", ".pdf", ".txt", ".md", ".markdown"}

# Explicitly superseded product doctrine.  Kept for repository history if desired, but
# never registered or embedded.  This protects production even when a patch is copied
# over an existing checkout and the old files are still present on disk.
SUPERSEDED_FILENAMES = {
    "5_1_ALPHA_Compute_Overview_v2.0.docx",
    "5_2_ALPHA Core Product Overview_V2.0.docx",
    "alpha_compute_problemology_public.md",
    "alpha_core_problemology_public.md",
    "Brand Story of itriX.docx",
    "WP_Alpha Compute Core.docx",
}

# Folder name -> effective disclosure level.
# Product/research knowledge is visitor-readable by default.  Operational internals and
# customer-specific contract material are still outside the public knowledge corpus.
FOLDER_DISCLOSURE = {
    "public": "public",
    "controlled_public": "public",
    "nda_only": "public",
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
    # Canonical documents that define BOTH products belong to the company/product
    # corpus rather than being hidden in one side of the product split.
    if ("alpha compute" in n or "alpha_compute" in n) and ("alpha core" in n or "alpha_core" in n):
        return "company"
    if "itrix_product_canonical" in n or "itrix company overview" in n or "itrix_company_overview" in n:
        return "company"
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
    # AI-sales-platform/build/operations documents are not company/product knowledge.
    # Keep them in general so the visitor-facing retriever can exclude them without
    # changing any journey or disclosure state.
    if any(token in n for token in (
        "theme system", "architecture flow", "operations command", "milestone",
        "functional specification", "product requirement", "build package",
        "ux & content blueprint", "wireframe", "visitor journey", "website personas",
        "building guideline", "execution plan", "knowledge core input request",
    )):
        return "general"
    # Company / brand / investor / project-direction materials.
    if (
        "brand story" in n
        or "kickoff" in n
        or "investor" in n
        or "playbook" in n
    ):
        return "company"
    # Everything else (website build / specs / wireframes / personas / journey / templates).
    return "general"


def title_for(path: Path) -> str:
    stem = path.stem
    # Tidy export-copy noise without accidentally turning a real v2.4 source into
    # "... .4". Version text is useful for source precedence and is therefore kept.
    stem = re.sub(r"\s+\([12]\)$", "", stem)
    return re.sub(r"\s+", " ", stem.replace("_", " ")).strip()


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
        assert_not_attachment_store(base)

        created = existing = skipped = 0
        for folder, disclosure in FOLDER_DISCLOSURE.items():
            d = base / folder
            if not d.exists():
                continue
            for f in sorted(d.iterdir()):
                if not f.is_file():
                    continue
                if f.name in SUPERSEDED_FILENAMES:
                    skipped += 1
                    self.stdout.write(self.style.WARNING(f"  skip (superseded): {folder}/{f.name}"))
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

                # POSIX FORM, ALWAYS. `str(f)` gives backslashes on Windows and forward
                # slashes on Linux, so the same file registered from a dev machine and
                # from the Railway container produced TWO different keys and therefore
                # TWO rows — each with its own UUID and its own full set of vectors
                # (`f"{document.id}:{chunk.index}"`). That is what duplicated the whole
                # corpus on 2026-08-07.
                #
                # `as_posix()` is the same string on every platform, so the idempotence
                # this command's docstring already claimed is now actually true.
                try:
                    canonical_path = f.resolve().relative_to(Path(settings.BASE_DIR).resolve()).as_posix()
                except ValueError:
                    canonical_path = f.as_posix()
                obj, made = KnowledgeDocument.objects.get_or_create(
                    file_path=canonical_path,
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
                    # Registration is also reconciliation: source policy or namespace
                    # rules may have changed since the row was first created.
                    updates = []
                    if obj.title != title:
                        obj.title = title
                        updates.append("title")
                    if obj.namespace != ns:
                        obj.namespace = ns
                        updates.append("namespace")
                    if obj.disclosure_level != disclosure:
                        obj.disclosure_level = disclosure
                        updates.append("disclosure_level")
                    if updates:
                        obj.ingestion_status = "PENDING"
                        updates.append("ingestion_status")
                        obj.save(update_fields=updates + ["updated_at"])
                        self.stdout.write(self.style.WARNING(f"  ~ reconciled [{disclosure:17}] [{ns:13}] {title}"))
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
