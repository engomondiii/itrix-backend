"""
THE ATTACHMENT REVIEW QUEUE, and RELEASE WITH A REASON (Backend v7.1 Phase 2).

── THE PROPERTY THESE TESTS EXIST FOR ──────────────────────────────────────

Releasing a quarantined file is the single most dangerous action on Surface 2: it takes a
file the system decided was unsafe and makes it readable by the extraction pipeline.

The reason is enforced at the API, not the UI. A UI-only requirement disappears the moment
anyone calls the endpoint directly — and the entire value of the reason is that it exists
LATER, when someone asks why a file the scanner objected to was processed.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def _team_client(role: str = "ASSESSMENT"):
    from django.contrib.auth import get_user_model
    from rest_framework.test import APIClient

    User = get_user_model()
    user = User.objects.create_user(
        email=f"{role.lower()}-att@itrix.test",
        password="a-long-enough-password",
        role=role,
        is_active=True,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _attachment(**kwargs):
    from apps.attachments.models import Attachment, AttachmentStatus
    from apps.conversations.services import threads as thread_svc

    thread = kwargs.pop("thread", None) or thread_svc.create_thread(visitor_session="sess-att")
    defaults = {
        "thread": thread,
        "filename": "architecture.pdf",
        "declared_mime": "application/pdf",
        "detected_mime": "application/pdf",
        "bytes": 4096,
        "sha256": "a" * 64,
        "blob_key": "blob/att-1",
        "status": AttachmentStatus.QUARANTINED,
        "risk_flags": ["archive_depth"],
        "uploaded_by_kind": "visitor",
    }
    defaults.update(kwargs)
    return Attachment.objects.create(**defaults)


def _scan(attachment, verdict="suspicious", detail="Nested archive exceeded depth 4."):
    from apps.attachments.models import AttachmentScan

    return AttachmentScan.objects.create(
        attachment=attachment, engine="builtin", verdict=verdict, detail=detail
    )


# ─────────────────────────────────────────────────────────────────────────────
# The queue
# ─────────────────────────────────────────────────────────────────────────────
def test_the_queue_shows_quarantined_and_failed_only():
    from apps.attachments.models import AttachmentStatus

    q = _attachment(filename="quarantined.pdf", status=AttachmentStatus.QUARANTINED)
    f = _attachment(filename="failed.pdf", status=AttachmentStatus.FAILED)
    _attachment(filename="ready.pdf", status=AttachmentStatus.READY)

    names = [r["filename"] for r in _team_client().get("/api/v1/cockpit/attachments/").json()["results"]]
    assert "quarantined.pdf" in names
    assert "failed.pdf" in names
    assert "ready.pdf" not in names
    assert {str(q.id), str(f.id)}


def test_the_queue_is_oldest_first():
    """
    Unlike every other queue here. A quarantined attachment is a visitor's document in limbo:
    they uploaded it, the surface said it was being checked, and nothing has happened since.
    Newest-first would leave the oldest waiting indefinitely — the outcome the visitor
    experiences directly.
    """
    first = _attachment(filename="oldest.pdf")
    second = _attachment(filename="newest.pdf")
    rows = _team_client().get("/api/v1/cockpit/attachments/").json()["results"]
    order = [r["filename"] for r in rows]
    assert order.index("oldest.pdf") < order.index("newest.pdf")
    assert first.created_at <= second.created_at


def test_a_row_shows_why_the_scanner_objected():
    """
    Without this the operator is being asked to overrule a decision whose grounds they cannot
    see — which is not a decision, it is a coin toss with an audit trail.
    """
    att = _attachment()
    _scan(att, verdict="suspicious", detail="Nested archive exceeded depth 4.")

    row = next(
        r for r in _team_client().get("/api/v1/cockpit/attachments/").json()["results"]
        if r["attachmentId"] == str(att.id)
    )
    assert row["scanVerdict"] == "suspicious"
    assert "depth 4" in row["scanDetail"]


def test_a_row_shows_both_mimes():
    """A declared/detected mismatch is itself a signal, and showing only one hides it."""
    att = _attachment(declared_mime="application/pdf", detected_mime="application/zip")
    row = next(
        r for r in _team_client().get("/api/v1/cockpit/attachments/").json()["results"]
        if r["attachmentId"] == str(att.id)
    )
    assert row["declaredMime"] == "application/pdf"
    assert row["detectedMime"] == "application/zip"


def test_pre_nda_files_are_counted_separately():
    """
    Shortened retention means a pre-NDA file can EXPIRE while waiting for a decision — and a
    file that expired unreviewed is a decision made by a timer.
    """
    _attachment(pre_nda=True)
    _attachment(pre_nda=False)
    summary = _team_client().get("/api/v1/cockpit/attachments/").json()["summary"]
    assert summary["preNdaAwaitingReview"] == 1
    assert summary["quarantined"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# Release
# ─────────────────────────────────────────────────────────────────────────────
def test_release_without_a_reason_is_refused():
    att = _attachment()
    response = _team_client().post(f"/api/v1/cockpit/attachments/{att.id}/release/", {}, format="json")
    assert response.status_code == 400
    # The refusal says WHY, so the operator can supply what is missing rather than guessing.
    assert "reason" in response.json()["detail"].lower()

    att.refresh_from_db()
    assert att.status == "quarantined"


def test_a_click_length_reason_is_refused():
    """"ok" and "." are a click, not a reason."""
    att = _attachment()
    response = _team_client().post(
        f"/api/v1/cockpit/attachments/{att.id}/release/", {"reason": "ok"}, format="json"
    )
    assert response.status_code == 400
    att.refresh_from_db()
    assert att.status == "quarantined"


def test_release_with_a_reason_succeeds_and_writes_the_audit_row():
    from apps.attachments.models import AttachmentAuditEntry

    att = _attachment()
    response = _team_client("ADMIN").post(
        f"/api/v1/cockpit/attachments/{att.id}/release/",
        {"reason": "False positive: the nested zip is a vendor SDK, verified by hand."},
        format="json",
    )
    assert response.status_code == 200

    att.refresh_from_db()
    # `scanned`, NOT `ready`: the file is now eligible for extraction. Claiming `ready` would
    # say extraction had happened when the pipeline still has to run.
    assert att.status == "scanned"

    entry = AttachmentAuditEntry.objects.filter(attachment=att, action="release").first()
    assert entry is not None
    assert "vendor SDK" in entry.purpose
    assert entry.plane == "team"
    assert "admin" in entry.subject


def test_the_audit_row_and_the_status_change_are_one_transaction():
    """
    A release whose audit row failed to write is a release nobody can account for. If the
    audit insert raises, the status change must not survive.
    """
    from unittest.mock import patch

    from apps.attachments.models import AttachmentAuditEntry

    att = _attachment()
    with patch.object(
        AttachmentAuditEntry.objects, "create", side_effect=RuntimeError("audit down")
    ):
        with pytest.raises(RuntimeError):
            from apps.cockpit.services import attachment_review

            attachment_review.release(
                str(att.id),
                user=type("U", (), {"email": "a@b.c", "role": "ADMIN"})(),
                reason="A reason long enough to pass the floor.",
            )

    att.refresh_from_db()
    assert att.status == "quarantined", "the status change survived a failed audit write"


def test_a_viewer_cannot_release():
    """
    A read-only role releasing a file the scanner objected to would make "read-only"
    meaningless in the one place it matters most.
    """
    att = _attachment()
    response = _team_client("VIEWER").post(
        f"/api/v1/cockpit/attachments/{att.id}/release/",
        {"reason": "A reason long enough to pass the floor."},
        format="json",
    )
    assert response.status_code == 403
    att.refresh_from_db()
    assert att.status == "quarantined"


def test_a_deleted_attachment_cannot_be_released():
    """Releasing it would resurrect something the platform promised was gone."""
    from django.utils import timezone

    att = _attachment(deleted_at=timezone.now())
    response = _team_client("ADMIN").post(
        f"/api/v1/cockpit/attachments/{att.id}/release/",
        {"reason": "A reason long enough to pass the floor."},
        format="json",
    )
    assert response.status_code == 400
    assert "deleted" in response.json()["detail"].lower()


def test_only_a_quarantined_attachment_can_be_released():
    from apps.attachments.models import AttachmentStatus

    att = _attachment(status=AttachmentStatus.READY)
    response = _team_client("ADMIN").post(
        f"/api/v1/cockpit/attachments/{att.id}/release/",
        {"reason": "A reason long enough to pass the floor."},
        format="json",
    )
    assert response.status_code == 400


def test_release_does_not_change_the_pre_nda_flag_or_retention():
    """
    A release makes a file READABLE by the pipeline. It does not make it more shareable — an
    attachment's level is capped by the plane that uploaded it and cannot be raised
    (§19.7 rule 4).
    """
    from django.utils import timezone

    expiry = timezone.now() + timezone.timedelta(days=7)
    att = _attachment(pre_nda=True, retention_expires_at=expiry)
    _team_client("ADMIN").post(
        f"/api/v1/cockpit/attachments/{att.id}/release/",
        {"reason": "Verified by hand against the customer's own SDK listing."},
        format="json",
    )
    att.refresh_from_db()
    assert att.pre_nda is True
    assert att.retention_expires_at == expiry


# ─────────────────────────────────────────────────────────────────────────────
# Quarantine — tightening is always permitted
# ─────────────────────────────────────────────────────────────────────────────
def test_quarantine_also_requires_a_reason():
    """The customer sent this document and may ask why it was withheld."""
    from apps.attachments.models import AttachmentStatus

    att = _attachment(status=AttachmentStatus.READY)
    response = _team_client("ADMIN").post(
        f"/api/v1/cockpit/attachments/{att.id}/quarantine/", {"reason": "no"}, format="json"
    )
    assert response.status_code == 400
    att.refresh_from_db()
    assert att.status == "ready"


def test_quarantine_works_from_any_state():
    """A file already extracted can still be quarantined if a human notices what the scanner did not."""
    from apps.attachments.models import AttachmentStatus

    att = _attachment(status=AttachmentStatus.READY)
    response = _team_client("ADMIN").post(
        f"/api/v1/cockpit/attachments/{att.id}/quarantine/",
        {"reason": "Contains a third party's confidential benchmark; withheld pending review."},
        format="json",
    )
    assert response.status_code == 200
    att.refresh_from_db()
    assert att.status == "quarantined"


def test_the_detail_carries_the_audit_trail():
    """
    Audit rows survive the attachment being purged. A purge that erased its own trail would
    make the retention guarantee unverifiable — which is the same as not having one.
    """
    att = _attachment()
    _scan(att)
    _team_client("ADMIN").post(
        f"/api/v1/cockpit/attachments/{att.id}/release/",
        {"reason": "False positive confirmed against the vendor manifest."},
        format="json",
    )

    body = _team_client().get(f"/api/v1/cockpit/attachments/{att.id}/").json()
    assert any(a["action"] == "release" for a in body["audit"])
    assert body["scans"][0]["verdict"] == "suspicious"
