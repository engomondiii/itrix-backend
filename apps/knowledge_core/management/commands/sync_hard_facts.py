"""Synchronize owner-verified hard facts supported by the authoritative source pack.

This command deliberately records unknown official identifiers as blank.  Internal
references (P...KR) are retained only on role-restricted registry rows and are never a
substitute for an official application/grant identifier.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.knowledge_core.canonical_taxonomy import PRODUCT_NAMES, TECHNOLOGIES
from apps.knowledge_core.models import DisclosureLevel, HardFact, KnowledgeDocument, SourceAuthority


FACTS = (
    {
        "key": "itrix-current-product-catalogue",
        "category": HardFact.Category.CORPORATE,
        "public_statement": f"itriX currently has three products: {', '.join(PRODUCT_NAMES[:-1])} and {PRODUCT_NAMES[-1]}.",
        "publication_status": "current September 2026 product taxonomy",
        "source_reference": "knowledge_docs/public/itrix_product_canonical_v3_5.md",
        "disclosure_level": DisclosureLevel.PUBLIC,
        "approved_audience": ["public", "visitor", "customer", "general"],
        "claim_ceiling": 1,
    },
    {
        "key": "itrix-current-technology-taxonomy",
        "category": HardFact.Category.CORPORATE,
        "public_statement": f"PRISM, AXIOM, AXIOM-TENSOR, CRE, FQNM and QNTA are itriX technologies rather than separately sold products.",
        "publication_status": "current September 2026 technology taxonomy",
        "source_reference": "knowledge_docs/public/itrix_product_canonical_v3_5.md",
        "disclosure_level": DisclosureLevel.PUBLIC,
        "approved_audience": ["public", "visitor", "customer", "general"],
        "claim_ceiling": 1,
    },
    {
        "key": "astop-prism-entity-types",
        "category": HardFact.Category.CORPORATE,
        "public_statement": "ASTOP is itriX's observation product and PRISM is the observation technology/architecture behind it; PRISM is not a separately sold product.",
        "publication_status": "current September 2026 product/technology taxonomy",
        "source_reference": "knowledge_docs/public/itrix_product_canonical_v3_5.md",
        "disclosure_level": DisclosureLevel.PUBLIC,
        "approved_audience": ["public", "visitor", "customer", "general"],
        "claim_ceiling": 1,
    },
    {
        "key": "kr-patent-applications-public-summary",
        "category": HardFact.Category.PATENT,
        "public_statement": "itriX has three Korean patent applications across the AXIOM, CRE and FQNM technology families.",
        "jurisdiction": "Republic of Korea",
        "publication_status": "applications / filings; grant status not verified in the authoritative source pack",
        "prosecution_status": "application status only",
        "source_reference": "Knowledge Core AXIOM/CRE/FQNM Overview v2.0 source set",
        "disclosure_level": DisclosureLevel.PUBLIC,
        "claim_ceiling": 1,
    },
    {
        "key": "axiom-kr-filing-internal",
        "category": HardFact.Category.PATENT,
        "jurisdiction": "Republic of Korea",
        "internal_reference": "P260-07KR",
        "publication_status": "filing/application reference in source material",
        "prosecution_status": "grant not verified",
        "source_reference": "4_1_AXIOM_Overview_v2.0.docx",
        "disclosure_level": DisclosureLevel.INTERNAL_ONLY,
        "claim_ceiling": 1,
    },
    {
        "key": "cre-kr-filing-internal",
        "category": HardFact.Category.PATENT,
        "jurisdiction": "Republic of Korea",
        "internal_reference": "P253-84KR",
        "publication_status": "filing/application reference in source material",
        "prosecution_status": "grant not verified",
        "source_reference": "4_2_CRE_Overview_v2.0.docx",
        "disclosure_level": DisclosureLevel.INTERNAL_ONLY,
        "claim_ceiling": 1,
    },
    {
        "key": "fqnm-kr-filing-internal",
        "category": HardFact.Category.PATENT,
        "jurisdiction": "Republic of Korea",
        "internal_reference": "P253-18KR",
        "publication_status": "filing/application reference in source material",
        "prosecution_status": "grant not verified",
        "source_reference": "4_3_FQNM_Overview_v2.0.docx",
        "disclosure_level": DisclosureLevel.INTERNAL_ONLY,
        "claim_ceiling": 1,
    },
)


class Command(BaseCommand):
    help = "Synchronize the structured authoritative hard-fact registry."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        now = timezone.now()
        for fact in FACTS:
            source_reference = str(fact.get("source_reference") or "")
            source_document = None
            if source_reference.startswith("knowledge_docs/"):
                source_document = KnowledgeDocument.objects.filter(
                    file_path=source_reference, is_current=True
                ).first()
            values = {
                **fact,
                "source_authority": SourceAuthority.AUTHORITATIVE,
                "is_current": True,
                "official_application_number": "",
                "verified_grant_number": "",
                "last_verified_at": now,
                "source_document": source_document,
            }
            key = values.pop("key")
            if options["dry_run"]:
                self.stdout.write(f"would sync {key}: {values['publication_status']}")
                continue
            HardFact.objects.update_or_create(key=key, defaults=values)
            self.stdout.write(self.style.SUCCESS(f"synced {key}"))
