"""
SCAN STRICTLY PRECEDES EXTRACTION (Backend v6.0 §4.3).

    An extraction that runs on an unscanned blob is a DEFECT WITH A NAMED TEST.

This is that test. It asserts against DATA — the presence of a clean scan row — rather
than against call order, because two functions called in the right sequence today can be
reordered tomorrow.
"""

from __future__ import annotations

from unittest.mock import patch

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
    import io
    import zipfile

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


def test_external_av_error_quarantines_a_built_in_clean_file(thread, settings):
    """A scanner timeout/crash is unknown, never permission to extract."""
    settings.ATTACHMENT_AV_COMMAND = "clamscan --no-summary"
    attachment = _stage(thread)
    with patch(
        "apps.attachments.services.scanner._external_av",
        return_value=(AttachmentScan.Verdict.ERROR, "scanner timed out"),
    ):
        record = scanner.scan(attachment)
    attachment.refresh_from_db()
    assert record.verdict == AttachmentScan.Verdict.ERROR
    assert attachment.status == AttachmentStatus.QUARANTINED
    assert "av:error" in attachment.risk_flags


def test_external_clean_cannot_override_built_in_archive_bomb(thread, settings):
    """A clean external signature scan never erases a deterministic bomb finding."""
    import io
    import zipfile

    settings.ATTACHMENT_AV_COMMAND = "clamscan --no-summary"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("big.txt", b"0" * 20_000_000)
    attachment = _stage(thread, name="bomb.zip", data=buffer.getvalue())

    with patch(
        "apps.attachments.services.scanner._external_av",
        return_value=(AttachmentScan.Verdict.CLEAN, "clean"),
    ):
        record = scanner.scan(attachment)
    attachment.refresh_from_db()
    assert record.verdict == AttachmentScan.Verdict.MALICIOUS
    assert attachment.status == AttachmentStatus.QUARANTINED
    assert "archive_bomb" in attachment.risk_flags
