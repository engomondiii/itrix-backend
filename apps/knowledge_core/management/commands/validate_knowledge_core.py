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
from django.db.models import Count, Q
from django.utils import timezone
import re

from apps.knowledge_core.models import IngestionStatus, KnowledgeChunk, KnowledgeDocument
from apps.knowledge_core.services.namespace_router import CANONICAL_NAMESPACES
from apps.knowledge_core.management.commands.register_knowledge_docs import FOLDER_DISCLOSURE


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_NEGATION = re.compile(r"\b(?:not|never|no|does\s+not|do\s+not|is\s+not|isn't|cannot|can't|without)\b", re.I)
_TECH_ENTITY = r"(?:PRISM|AXIOM(?:-TENSOR)?|CRE|FQNM|QNTA)"


def current_public_conflicts(text: str) -> list[str]:
    """Return positive, current-doctrine conflicts from one public-safe text chunk.

    This deliberately reasons at sentence level for commercialization claims so negative
    governance such as ``ASTOP is not self-service`` does not fail merely because it
    contains the prohibited phrase. Historical sources are filtered by the caller via
    ``document.is_current`` and never reach this function during validation.
    """
    value = str(text or "")
    problems: list[str] = []

    if re.search(r"what does itrix actually sell\??\s*two complementary but independent infrastructure products", value, re.I | re.S):
        problems.append("two-product public catalogue")
    if re.search(r"\bitrix\s+(?:currently\s+)?has\s+(?:only\s+)?two\s+products\b", value, re.I):
        problems.append("two-product public catalogue")
    if re.search(rf"\bproducts?\s+(?:are|include|consist of|comprise)\b.{{0,120}}\b{_TECH_ENTITY}\b", value, re.I | re.S):
        problems.append("technology classified as sold product")

    if re.search(r"(?:complete|current|all)\s+(?:itrix\s+)?products?|what does itrix actually sell", value, re.I | re.S):
        if "ALPHA Compute" in value and "ALPHA Core" in value and "ASTOP" not in value:
            problems.append("complete product catalogue omits ASTOP")

    for sentence in _SENTENCE_SPLIT.split(value):
        sentence = sentence.strip()
        if not sentence or _NEGATION.search(sentence):
            continue
        if re.search(r"\bASTOP\b.{0,80}\bself[- ]service\b|\bself[- ]service\b.{0,80}\bASTOP\b", sentence, re.I):
            problems.append("ASTOP self-service claim")
        if re.search(r"\bASTOP\s+(?:Team|Pro|Business|Enterprise)\b", sentence, re.I):
            problems.append("obsolete ASTOP tier model")
        if re.search(r"\$(?:99|499|12(?:,?000)|100(?:,?000))\b", sentence) and re.search(r"\b(?:ASTOP|Team|Pro|Business|Enterprise|price|pricing|plan|tier)\b", sentence, re.I):
            problems.append("obsolete public ASTOP pricing")
        if re.search(r"\b(?:buy|purchase|checkout)\b.{0,100}\bASTOP\b|\bASTOP\b.{0,100}\b(?:buy|purchase|checkout)\b", sentence, re.I):
            problems.append("ASTOP public checkout")
        if re.search(r"\b(?:public|anonymous|anyone|visitor)\b.{0,120}\b(?:executable|binary|download|installer)\b", sentence, re.I):
            problems.append("public unrestricted executable access")
        if re.search(r"\b(?:money[- ]back|refund)\s+guarantee\b", sentence, re.I):
            problems.append("obsolete money-back guarantee")

    # Stable order and no duplicate labels when one chunk repeats the same doctrine.
    return list(dict.fromkeys(problems))


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
            is_current=True, ingestion_status=IngestionStatus.COMPLETE, chunk_count=0
        ).exclude(disclosure_level="prohibited")
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
            file_path__icontains="itrix_product_canonical_v3_5.md",
            is_current=True,
            source_authority="authoritative",
            ingestion_status=IngestionStatus.COMPLETE,
            disclosure_level="public",
        )
        if canonical.exists():
            doc = canonical.first()
            self.stdout.write(self.style.SUCCESS(f"  current: {doc.title} ({doc.chunk_count} chunks)"))
        else:
            self.stdout.write(self.style.ERROR("  ! Current September v3.5 product canonical is not authoritative/current/COMPLETE + public."))
            problems += 1

        old_current = KnowledgeDocument.objects.filter(is_current=True).filter(
            Q(file_path__icontains="itrix_product_canonical_v2_4.md")
            | Q(file_path__icontains="WP_ALPHA_Compute_Core_v2.4.docx")
        )
        if old_current.exists():
            problems += old_current.count()
            self.stdout.write(self.style.ERROR("  ! superseded ALPHA-only product source is still current"))

        # Content-level regression: current public chunks may explain historical claims,
        # but they may not assert the superseded catalogue as current doctrine.
        public_chunks = list(
            KnowledgeChunk.objects.select_related("document").filter(
                document__is_current=True,
                document__disclosure_level__in=["public", "controlled_public"],
            )
        )
        for chunk in public_chunks:
            for label in current_public_conflicts(chunk.text or ""):
                problems += 1
                self.stdout.write(self.style.ERROR(
                    f"  ! current public conflict ({label}): {chunk.document.file_path} chunk {chunk.chunk_index}"
                ))

        # ── September 2026 ASTOP / Sales Platform authority ─────────────────
        self.stdout.write(self.style.MIGRATE_HEADING("September 2026 governing sources"))
        required_sources = (
            ("ASTOP_Productization_GTM_Plan_v2.3", "internal_only", "authoritative"),
            ("itriX_AI_Sales_Platform_MVP_Guide_for_Fidel_v3.5", "internal_only", "authoritative"),
            ("itriX_White_Paper_v3.5", "internal_only", "authoritative"),
            ("prism-paper-current_v2", "controlled_public", "authoritative"),
            ("astop_prism_public_safe_v2_3", "public", "governing"),
            ("itriX_MVP_Acceptance_Rerun_Feedback_to_Fidel", "internal_only", "governing"),
        )
        for filename, level, authority in required_sources:
            row = KnowledgeDocument.objects.filter(
                file_path__icontains=filename, is_current=True, disclosure_level=level, source_authority=authority
            ).first()
            if row is None:
                problems += 1
                self.stdout.write(self.style.ERROR(f"  ! missing/currentness-tier mismatch: {filename}"))
            else:
                self.stdout.write(self.style.SUCCESS(f"  current: {filename} [{level}/{authority}]"))

        stale_astop = KnowledgeDocument.objects.filter(is_current=True).filter(
            Q(title__iexact="ASTOP Team")
            | Q(title__icontains="ASTOP Team ")
            | Q(title__iexact="ASTOP Pro")
            | Q(title__icontains="ASTOP Pro ")
        )
        if stale_astop.exists():
            problems += stale_astop.count()
            self.stdout.write(self.style.ERROR("  ! superseded ASTOP tier source is still current"))

        # Folder placement is itself an authorization decision. Validate exact policy
        # parity instead of incorrectly requiring controlled/agreement-gated sources to
        # become public. That would turn a health check into a disclosure downgrade.
        self.stdout.write(self.style.MIGRATE_HEADING("Disclosure folder parity"))
        drift = []
        # Historical source rows are retained for audit/reconciliation but are
        # deliberately non-current and have no retrievable chunks. Folder parity
        # applies to active Knowledge sources only.
        for doc in KnowledgeDocument.objects.filter(is_current=True):
            parts = str(doc.file_path or "").replace("\\", "/").split("/")
            expected = None
            if "knowledge_docs" in parts:
                i = parts.index("knowledge_docs")
                if i + 1 < len(parts):
                    expected = FOLDER_DISCLOSURE.get(parts[i + 1])
            if expected and doc.disclosure_level != expected:
                drift.append((doc, expected))
        if drift:
            problems += len(drift)
            for doc, expected in drift:
                self.stdout.write(self.style.ERROR(
                    f"  ! {doc.file_path}: row={doc.disclosure_level} folder={expected}"
                ))
        else:
            self.stdout.write(self.style.SUCCESS("  all registered source tiers match their folders"))

        # Currentness metadata must not quietly age past an owner-supplied review date.
        today = timezone.now().date()
        overdue = KnowledgeDocument.objects.filter(is_current=True, review_after__lt=today)
        if overdue.exists():
            problems += overdue.count()
            self.stdout.write(self.style.ERROR(f"  ! {overdue.count()} current source(s) are past review_after."))
        stale_with_chunks = KnowledgeDocument.objects.filter(is_current=False, chunks__isnull=False).distinct()
        if stale_with_chunks.exists():
            problems += stale_with_chunks.count()
            self.stdout.write(self.style.ERROR(
                f"  ! {stale_with_chunks.count()} non-current source(s) still have retrievable chunks."
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
