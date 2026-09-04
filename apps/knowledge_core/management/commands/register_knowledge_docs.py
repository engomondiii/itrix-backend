"""
``python manage.py register_knowledge_docs``

Walks the ``knowledge_docs/`` tree and registers a ``KnowledgeDocument`` for every
ingestible file (``.docx`` / ``.pdf`` / ``.txt`` / ``.md``), inferring:

* **disclosure_level** from the source folder itself. Folder placement is an
  authorization decision; registration never silently downgrades controlled/NDA material
  into public, and
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
    "README_Astop.txt",
}

# Folder name -> exact disclosure level.  The folder is the decision: registration
# must never reinterpret a more restrictive source folder as public.
FOLDER_DISCLOSURE = {
    "public": "public",
    "controlled_public": "controlled_public",
    "authorized": "authorized",
    "nda_only": "nda_only",
    "customer_contract": "customer_contract",
    "internal_only": "internal_only",
    "prohibited": "prohibited",
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

    if "astop" in n or "prism" in n:
        return "astop"
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



def source_authority_for(filename: str) -> tuple[str, bool, str]:
    """Conservative source-precedence metadata inferred only from explicit version/status cues."""
    n = filename.lower()
    if filename in SUPERSEDED_FILENAMES or any(x in n for x in ("legacy", "superseded", "archive")):
        return "legacy", False, ""
    if "productization_gtm_plan_v2.3" in n or "sales_platform_mvp_guide_for_fidel_v3.5" in n:
        return "authoritative", True, "September 2026 governing commercialization / implementation source"
    if "white_paper_v3.5" in n:
        return "authoritative", True, "Current canonical product/technology taxonomy and evidence boundaries"
    if "prism-paper-current_v2" in n:
        return "authoritative", True, "Current PRISM primary research evidence"
    if "astop_prism_public_safe_v2_3" in n:
        return "governing", True, "Approved public-safe synthesis bounded by GTM v2.3 and PRISM evidence"
    if "astop_technical_capabilities_current" in n or "axiom_tensor_qnta_current_controlled" in n:
        return "governing", True, "Current controlled technical synthesis"
    if "mvp_acceptance_rerun_feedback" in n:
        return "governing", True, "Latest targeted MVP acceptance corrections"
    if any(x in n for x in ("canonical", "register", "executed")):
        return "authoritative", True, "Explicit canonical/register source"
    if "itrix_company_overview_public" in n:
        return "governing", True, "Current public company/technology synthesis"
    if any(x in n for x in ("master technical architecture", "complete backend structure", "complete surface", "legal instruments", "content and flow playbook", "_overview_v2.0", "overview v2.0", "unified mathematical", "v2_4", "v2.4")):
        return "governing", True, "Current approved governing source"
    return "working", True, ""


def technology_family_for(filename: str) -> str:
    n = filename.lower()
    if "astop" in n and "prism" not in n:
        return "astop"
    if "prism" in n:
        return "prism"
    if "axiom_tensor" in n or "axiom-tensor" in n:
        return "axiom_tensor"
    if "qnta" in n:
        return "qnta"
    if "axiom" in n and not any(x in n for x in ("alpha", "unified")):
        return "axiom"
    if ("cre" in n or "conjugation" in n) and not any(x in n for x in ("alpha", "unified")):
        return "cre"
    if "fqnm" in n or "quantised" in n or "quantized" in n:
        return "fqnm"
    if "alpha compute" in n or "alpha_compute" in n:
        if "alpha core" not in n and "alpha_core" not in n:
            return "alpha_compute"
    if "alpha core" in n or "alpha_core" in n:
        if "alpha compute" not in n and "alpha_compute" not in n:
            return "alpha_core"
    if any(x in n for x in ("boundary-aware", "boundary aware", "unified mathematical")):
        return "cross_cutting"
    return "general"


def governance_metadata_for(filename: str, disclosure: str) -> dict:
    """Explicit September-2026 metadata for authority, audience, evidence and claim ceilings."""
    n = filename.lower()
    meta = {
        "approved_audience": ["internal"] if disclosure == "internal_only" else ["public", "visitor", "customer"],
        "allowed_journey_stages": ["PUBLIC-SAFE", "QUALIFIED", "NDA", "EVALUATION", "LICENSED"],
        "claim_ceiling": 2 if disclosure in {"public", "controlled_public"} else 3,
        "entity_type": "mixed",
        "evidence_status": "mixed",
    }
    if "productization_gtm_plan_v2.3" in n:
        meta.update(approved_audience=["internal", "commercial"], allowed_journey_stages=["QUALIFIED", "NDA", "EVALUATION", "LICENSED"], claim_ceiling=3, entity_type="governance", evidence_status="governance")
    elif "sales_platform_mvp_guide_for_fidel_v3.5" in n:
        meta.update(approved_audience=["internal", "implementation"], claim_ceiling=3, entity_type="platform", evidence_status="governance")
    elif "white_paper_v3.5" in n:
        meta.update(approved_audience=["internal"], claim_ceiling=3, entity_type="mixed", evidence_status="mixed")
    elif "prism-paper-current_v2" in n:
        meta.update(claim_ceiling=2, entity_type="research", evidence_status="experimental")
    elif "prism_and_astop_explained" in n or "astop_prism_public_safe" in n:
        meta.update(claim_ceiling=2, entity_type="mixed", evidence_status="experimental")
    elif "astop_technical_capabilities_current" in n:
        meta.update(approved_audience=["internal", "technical"], claim_ceiling=3, entity_type="product", evidence_status="implemented")
    elif "axiom_tensor_qnta_current_controlled" in n:
        meta.update(approved_audience=["internal", "technical"], claim_ceiling=2, entity_type="technology", evidence_status="experimental")
    elif "mvp_acceptance_rerun_feedback" in n:
        meta.update(approved_audience=["internal", "implementation"], claim_ceiling=3, entity_type="governance", evidence_status="governance")
    return meta


def paraphrase_for(disclosure: str) -> str:
    if disclosure in {"internal_only", "prohibited"}:
        return "none"
    if disclosure in {"authorized", "nda_only", "customer_contract"}:
        return "summary"
    return "approved"

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
        active_paths: set[str] = set()
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
                authority, is_current, canonical_rule = source_authority_for(f.name)
                family = technology_family_for(f.name)
                paraphrase = paraphrase_for(disclosure)
                governance = governance_metadata_for(f.name, disclosure)

                # POSIX FORM, ALWAYS. The active-path set is also the reconciliation
                # source: anything previously registered under knowledge_docs/ that is no
                # longer present/eligible is marked non-current after this walk.
                try:
                    canonical_path = f.resolve().relative_to(Path(settings.BASE_DIR).resolve()).as_posix()
                except ValueError:
                    canonical_path = f.as_posix()
                active_paths.add(canonical_path)

                if dry_run:
                    suffix = " [NO-EMBED]" if disclosure == "prohibited" else ""
                    self.stdout.write(f"  would register [{disclosure:17}] [{ns:13}] [{authority:13}] {title}{suffix}")
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
                obj, made = KnowledgeDocument.objects.get_or_create(
                    file_path=canonical_path,
                    defaults={
                        "title": title,
                        "namespace": ns,
                        "disclosure_level": disclosure,
                        "source_authority": authority,
                        "is_current": is_current,
                        "canonical_rule": canonical_rule,
                        "permitted_paraphrase": paraphrase,
                        "technology_family": family,
                        **governance,
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
                    for field, value in (
                        ("source_authority", authority),
                        ("is_current", is_current),
                        ("canonical_rule", canonical_rule),
                        ("permitted_paraphrase", paraphrase),
                        ("technology_family", family),
                        *((field, value) for field, value in governance.items()),
                    ):
                        if getattr(obj, field) != value:
                            setattr(obj, field, value)
                            updates.append(field)
                    if updates:
                        obj.ingestion_status = "PENDING"
                        updates.append("ingestion_status")
                        obj.save(update_fields=updates + ["updated_at"])
                        self.stdout.write(self.style.WARNING(f"  ~ reconciled [{disclosure:17}] [{ns:13}] {title}"))
                    else:
                        existing += 1
                        self.stdout.write(f"  = exists: {title}")

        if not dry_run:
            # A move, deletion or newly-superseded source must not leave its old row
            # current. Mark it non-current and remove local chunks immediately; a later
            # namespace re-ingest clears any old remote vectors before rebuilding only
            # current documents.
            stale = KnowledgeDocument.objects.filter(file_path__startswith="knowledge_docs/").exclude(
                file_path__in=sorted(active_paths)
            )
            stale_count = stale.count()
            for obj in stale:
                obj.chunks.all().delete()
                updates = []
                for field, value in (
                    ("is_current", False),
                    ("permitted_paraphrase", "none"),
                    ("chunk_count", 0),
                    ("ingestion_status", "COMPLETE"),
                ):
                    if getattr(obj, field) != value:
                        setattr(obj, field, value)
                        updates.append(field)
                if updates:
                    obj.save(update_fields=updates + ["updated_at"])
            if stale_count:
                self.stdout.write(self.style.WARNING(f"  ~ marked {stale_count} inactive source row(s) non-current"))

        verb = "Would register" if dry_run else "Registered"
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{verb} {created} document(s); {existing} already present; {skipped} skipped."
            )
        )
        if not dry_run:
            self.stdout.write("Next: python manage.py ingest_documents")
