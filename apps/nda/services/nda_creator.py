"""
NDA creator.

Creates (or returns) the NDA record for a lead, seeded with the standard checklist, and
moves the lead's status to NDA. Idempotent per lead.
"""

from __future__ import annotations

import logging

from apps.nda.models import NDARecord
from apps.nda.services.nda_checklist import default_checklist

logger = logging.getLogger("itrix")


def create_nda_for_lead(lead) -> NDARecord:
    existing = NDARecord.objects.filter(lead=lead).first()
    if existing:
        return existing
    nda = NDARecord.objects.create(
        lead=lead,
        lead_name=lead.company or lead.visitor_name or "Lead",
        company=lead.company or "",
        checklist=default_checklist(),
    )
    logger.info("NDA record created for lead %s", lead.id)
    return nda
