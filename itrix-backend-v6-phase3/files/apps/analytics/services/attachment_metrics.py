"""
Attachment analytics (Backend v6.0 §Phase 3).

    upload volume · type mix · extraction success · quarantine rate

── QUARANTINE RATE CUTS BOTH WAYS ───────────────────────────────────────────
A rising rate may mean an attack, or it may mean the scanner has become over-eager and is
quarantining ordinary files. Both need investigating, and the number alone does not
distinguish them — which is why ``quarantine_reasons`` breaks it down by risk flag.

Everything here is INTERNAL-ONLY: ``attachment_risk_flags`` is on the §10.5 list.
"""

from __future__ import annotations

import logging

from django.db.models import Count
from django.utils import timezone

logger = logging.getLogger("itrix")


def volume(*, window_days: int = 30) -> dict:
    from apps.attachments.models import Attachment

    since = timezone.now() - timezone.timedelta(days=window_days)
    qs = Attachment.objects.filter(created_at__gte=since)
    total_bytes = sum(qs.values_list("bytes", flat=True)) if qs.exists() else 0
    return {
        "uploads": qs.count(),
        "totalBytes": total_bytes,
        "preNda": qs.filter(pre_nda=True).count(),
        "windowDays": window_days,
    }


def type_mix(*, limit: int = 15) -> list[dict]:
    """What visitors actually send — which drives which handlers are worth improving."""
    from apps.attachments.models import Attachment

    rows = (
        Attachment.objects.exclude(detected_mime="")
        .values("detected_mime")
        .annotate(n=Count("id"))
        .order_by("-n")[:limit]
    )
    return [{"type": row["detected_mime"], "count": row["n"]} for row in rows]


def extraction_success() -> dict:
    """
    Extraction outcomes.

    ``metadataOnly`` is NOT a failure (§19.7 rule 4) and is reported separately from
    ``failed`` so nobody reads an opaque-binary rate as a defect rate.
    """
    from apps.attachments.models import AttachmentExtraction

    total = AttachmentExtraction.objects.count()
    if not total:
        return {"total": 0, "withText": 0, "metadataOnly": 0, "textRate": None}

    metadata_only = AttachmentExtraction.objects.filter(metadata_only=True).count()
    with_text = total - metadata_only
    return {
        "total": total,
        "withText": with_text,
        "metadataOnly": metadata_only,
        "textRate": round(with_text / total, 3),
    }


def quarantine_rate(*, window_days: int = 30) -> dict:
    from apps.attachments.models import Attachment, AttachmentStatus

    since = timezone.now() - timezone.timedelta(days=window_days)
    qs = Attachment.objects.filter(created_at__gte=since)
    total = qs.count()
    quarantined = qs.filter(status=AttachmentStatus.QUARANTINED).count()
    return {
        "total": total,
        "quarantined": quarantined,
        "rate": round(quarantined / total, 3) if total else None,
        "windowDays": window_days,
    }


def quarantine_reasons() -> dict:
    """
    Which risk flag drove each quarantine.

    Distinguishes "we are under attack" from "the scanner has become over-eager" — the
    rate alone cannot.
    """
    from apps.attachments.models import Attachment, AttachmentStatus

    counts: dict[str, int] = {}
    for attachment in Attachment.objects.filter(
        status=AttachmentStatus.QUARANTINED
    ).only("risk_flags"):
        for flag in attachment.risk_flags or []:
            key = str(flag).split(":")[0]
            counts[key] = counts.get(key, 0) + 1
    return counts


def retention_state() -> dict:
    """Purge health — the privacy obligation, made countable."""
    from apps.attachments.models import Attachment

    now = timezone.now()
    return {
        "live": Attachment.objects.filter(purged_at__isnull=True).count(),
        "purged": Attachment.objects.filter(purged_at__isnull=False).count(),
        "overdue": Attachment.objects.filter(
            purged_at__isnull=True, retention_expires_at__lt=now
        ).count(),
    }


def summary() -> dict:
    return {
        "volume": volume(),
        "typeMix": type_mix(),
        "extraction": extraction_success(),
        "quarantine": quarantine_rate(),
        "quarantineReasons": quarantine_reasons(),
        "retention": retention_state(),
    }
