"""
SCAN STRICTLY PRECEDES EXTRACTION (Backend v6.0 §4.3).

    An extraction that runs on an unscanned blob is a DEFECT WITH A NAMED TEST.

This is that test. It asserts against DATA — the presence of a clean scan row — rather
than against call order, because two functions called in the right sequence today can be
reordered tomorrow.
"""

from __future__ import annotations

import pytest

from apps.attachments.models import AttachmentScan, AttachmentStatus
from apps.attachments.services import extractor, intake, scanner

pytestmark = pytest.mark.django_db


def _stage(thread, name="notes.txt", data=b"Our solver drifts over long runs."):
    return intake.stage(thread=thread, filename=name, data=data, declared_mime="text/plain")


def test_extraction_refuses_without_a_scan(thread):
    """THE REGRESSION. No scan row at all means no extraction."""
    attachment = _stage(thread)
    assert not AttachmentScan.objects.filter(attachment=attachment).exists()
    with pytest.raises(extractor.ScanRequired):
        extractor.run(attachment)


def test_extraction_refuses_after_a_malicious_verdict(thread):
    attachment = _stage(thread)
    AttachmentScan.objects.create(
        attachment=attachment, verdict=AttachmentScan.Verdict.MALICIOUS
    )
    with pytest.raises(extractor.ScanRequired):
        extractor.run(attachment)


def test_extraction_refuses_after_an_error_verdict(thread):
    """
    'We could not tell' is not 'clean'. Treating an unscannable file as safe is how
    scanners get bypassed.
    """
    attachment = _stage(thread)
    AttachmentScan.objects.create(attachment=attachment, verdict=AttachmentScan.Verdict.ERROR)
    with pytest.raises(extractor.ScanRequired):
        extractor.run(attachment)


def test_extraction_proceeds_after_a_clean_scan(thread):
    attachment = _stage(thread)
    scanner.scan(attachment)
    attachment.refresh_from_db()
    assert attachment.status == AttachmentStatus.SCANNED

    extraction = extractor.run(attachment)
    assert extraction is not None
    attachment.refresh_from_db()
    assert attachment.status == AttachmentStatus.READY


def test_the_pipeline_quarantines_rather_than_extracting(thread):
    """A quarantined file is never handed to a parser."""
    from apps.attachments.models import AttachmentExtraction

    # A zip bomb: tiny compressed, enormous uncompressed.
    import io, zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("big.txt", b"0" * 20_000_000)
    attachment = _stage(thread, name="bomb.zip", data=buffer.getvalue())

    intake.process(attachment)
    attachment.refresh_from_db()
    assert attachment.status == AttachmentStatus.QUARANTINED
    assert not AttachmentExtraction.objects.filter(attachment=attachment).exists()


def test_a_clean_scan_row_must_actually_exist(thread):
    """``has_clean_scan`` requires a CLEAN row — absence of a bad one is not enough."""
    attachment = _stage(thread)
    assert scanner.has_clean_scan(attachment) is False
    AttachmentScan.objects.create(attachment=attachment, verdict=AttachmentScan.Verdict.CLEAN)
    assert scanner.has_clean_scan(attachment) is True
