"""Synchronize owner-verified hard facts supported by the authoritative source pack.

This command deliberately records unknown official identifiers as blank.  Internal
references (P...KR) are retained only on role-restricted registry rows and are never a
substitute for an official application/grant identifier.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.knowledge_core.models import DisclosureLevel, HardFact, SourceAuthority


FACTS = (
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
            values = {
                **fact,
                "source_authority": SourceAuthority.AUTHORITATIVE,
                "is_current": True,
                "official_application_number": "",
                "verified_grant_number": "",
                "last_verified_at": now,
            }
            key = values.pop("key")
            if options["dry_run"]:
                self.stdout.write(f"would sync {key}: {values['publication_status']}")
                continue
            HardFact.objects.update_or_create(key=key, defaults=values)
            self.stdout.write(self.style.SUCCESS(f"synced {key}"))
