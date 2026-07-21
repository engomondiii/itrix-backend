"""
VERIFIABLE VISITOR DELETE (Backend v6.0 §4.6 boundary 4, §4.7).

    A visitor can delete any attachment at ANY TIME, which purges the blob, the
    extraction and the derived excerpts, and IS VERIFIABLE.

The visitor is told "Removed. We have deleted this file and anything we read from it."
That is a claim somebody has to be able to check — so ``verify_purged`` exists, and these
tests exercise it.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.attachments import storage
from apps.attachments.models import (
    Attachment,
    AttachmentExcerpt,
    AttachmentExtraction,
    AttachmentStatus,
)
from apps.attachments.services import intake, retention

pytestmark = pytest.mark.django_db


def _ready(thread, name="doc.txt"):
    attachment = intake.stage(
        thread=thread, filename=name,
        data=b"Our CFD solver drifts over long simulations and memory movement dominates.",
        declared_mime="text/plain",
    )
    intake.process(attachment)
    attachment.refresh_from_db()
    return attachment


def test_delete_removes_all_three_artefacts(thread):
    attachment = _ready(thread)
    blob_key = attachment.blob_key
    assert storage.exists(blob_key)
    assert AttachmentExtraction.objects.filter(attachment=attachment).exists()

    retention.visitor_delete(attachment)
    attachment.refresh_from_db()

    assert not storage.exists(blob_key)
    assert not AttachmentExtraction.objects.filter(attachment=attachment).exists()
    assert not AttachmentExcerpt.objects.filter(attachment=attachment).exists()


def test_verify_purged_confirms_all_three(thread):
    attachment = _ready(thread)
    retention.visitor_delete(attachment)
    attachment.refresh_from_db()

    report = retention.verify_purged(attachment)
    assert report["blob_gone"] and report["extraction_gone"] and report["excerpts_gone"]
    assert report["verified"] is True


def test_verify_fails_when_a_blob_survives(thread):
    """The verifier must actually be able to FAIL, or it proves nothing."""
    attachment = _ready(thread)
    assert retention.verify_purged(attachment)["verified"] is False


def test_the_row_survives_as_an_audit_record(thread):
    """
    A deletion that leaves NO trace is indistinguishable from one that never happened.
    The row remains, marked purged, carrying its audit trail.
    """
    attachment = _ready(thread)
    retention.visitor_delete(attachment)
    attachment.refresh_from_db()

    assert Attachment.objects.filter(id=attachment.id).exists()
    assert attachment.status == AttachmentStatus.PURGED
    assert attachment.purged_at is not None
    assert attachment.audit_entries.filter(action="purge").exists()


def test_purge_is_idempotent(thread):
    attachment = _ready(thread)
    retention.visitor_delete(attachment)
    attachment.refresh_from_db()
    retention.visitor_delete(attachment)  # must not raise
    assert retention.verify_purged(attachment)["verified"] is True


def test_a_deleted_attachment_is_no_longer_downloadable(thread):
    attachment = _ready(thread)
    retention.visitor_delete(attachment)
    attachment.refresh_from_db()
    assert attachment.is_downloadable is False


def test_the_retention_sweep_purges_expired_pre_nda_files(thread):
    attachment = _ready(thread)
    Attachment.objects.filter(id=attachment.id).update(
        retention_expires_at=timezone.now() - timezone.timedelta(days=1)
    )
    summary = retention.sweep()
    assert summary["purged"] >= 1
    attachment.refresh_from_db()
    assert retention.verify_purged(attachment)["verified"] is True


def test_the_sweep_leaves_unexpired_files_alone(thread):
    attachment = _ready(thread)
    retention.sweep()
    attachment.refresh_from_db()
    assert attachment.purged_at is None
