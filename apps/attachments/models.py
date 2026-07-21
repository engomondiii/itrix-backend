"""
Attachment models (Backend v6.0 §4.1, Architecture v2.6 §19.7).

Accepting arbitrary files from unidentified visitors on a pre-NDA surface is the largest
new risk in v6.0. Three models carry it, and the SEPARATION between them is deliberate:

    Attachment           the file itself — bytes, hash, status, retention
    AttachmentScan       the AV / archive-bomb verdict, recorded BEFORE extraction
    AttachmentExtraction the extracted text, produced only AFTER a clean scan

Keeping the scan in its own table is what makes "scanned before extraction" auditable
rather than merely intended: an extraction row whose attachment has no clean scan row is
a detectable defect, and there is a named test for exactly that.

── THE FOUR HARD BOUNDARIES (§4.6) ──────────────────────────────────────────
1. An attachment NEVER raises a ceiling. disclosure_ceiling derives from the identity
   plane and NDA/contract state only.
2. An attachment is NEVER ingested into the Knowledge Core.
3. An attachment is SCOPED TO ITS THREAD.
4. A visitor can DELETE any attachment at any time, verifiably.

Boundary 1 is the one that matters most, and note where it is enforced: nowhere in this
file. There is deliberately no ``disclosure_level`` field on Attachment. A model that
cannot express a ceiling cannot raise one.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import BaseModel


class AttachmentStatus(models.TextChoices):
    """
    The pipeline, in order. Status only ever moves forward.

    ``quarantined`` and ``failed`` are terminal. ``purged`` means the bytes are gone but
    the row remains as an audit record — a deletion that leaves no trace is
    indistinguishable from a deletion that never happened.
    """

    STAGED = "staged", "Staged"
    SCANNING = "scanning", "Scanning"
    SCANNED = "scanned", "Scanned"
    EXTRACTING = "extracting", "Extracting"
    READY = "ready", "Ready"
    QUARANTINED = "quarantined", "Quarantined"
    FAILED = "failed", "Failed"
    PURGED = "purged", "Purged"


class Attachment(BaseModel):
    """
    One uploaded file.

    ``blob_key`` points OUTSIDE the web root. There is no field holding a public URL,
    because there is no public URL — downloads go through a signed, authorization-checked
    endpoint that sets ``Content-Disposition: attachment`` (§4.4).
    """

    class UploadedByKind(models.TextChoices):
        SESSION = "session", "Visitor session"
        CLIENT = "client", "Client"
        TEAM = "team", "Team"

    thread = models.ForeignKey(
        "conversations.Thread",
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    uploaded_by_kind = models.CharField(
        max_length=16, choices=UploadedByKind.choices, default=UploadedByKind.SESSION
    )
    # The session or client id that uploaded it. Used for the per-session abuse ceiling.
    uploaded_by_id = models.CharField(max_length=128, blank=True, default="", db_index=True)

    filename = models.CharField(max_length=512)
    # What the CLIENT claimed vs what we DETECTED. They are stored separately because a
    # mismatch is itself a risk signal — a .txt that sniffs as a ZIP is worth flagging.
    declared_mime = models.CharField(max_length=200, blank=True, default="")
    detected_mime = models.CharField(max_length=200, blank=True, default="")
    bytes = models.BigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True, default="", db_index=True)
    blob_key = models.CharField(max_length=512, blank=True, default="")

    status = models.CharField(
        max_length=16,
        choices=AttachmentStatus.choices,
        default=AttachmentStatus.STAGED,
        db_index=True,
    )

    # ── Pre-NDA restricted handling (§4.7) ───────────────────────────────────
    # Set at upload from the thread's ceiling. Carries a SHORTER retention window,
    # encryption at rest, and access restricted to the owning thread.
    pre_nda = models.BooleanField(default=True, db_index=True)
    retention_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    purged_at = models.DateTimeField(null=True, blank=True)

    # INTERNAL-ONLY (§10.5). Never on the anonymous or client plane.
    risk_flags = models.JSONField(default=list, blank=True)

    # What the visitor was told, when we could not read the file. Stored so the honest
    # message is durable rather than regenerated differently on each render.
    visitor_note = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Attachment"
        verbose_name_plural = "Attachments"
        indexes = [
            models.Index(fields=["thread", "status"]),
            models.Index(fields=["status", "retention_expires_at"]),
            models.Index(fields=["pre_nda", "retention_expires_at"]),
        ]

    def __str__(self) -> str:
        return f"Attachment({self.filename[:40]}, {self.status})"

    @property
    def is_readable(self) -> bool:
        """Whether extracted text exists and may be used as context."""
        return self.status == AttachmentStatus.READY

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None or self.status == AttachmentStatus.PURGED

    @property
    def is_downloadable(self) -> bool:
        """
        A quarantined file is NEVER previewable and NEVER downloadable without a
        deliberate, logged release (Surface 2 v5.0 §4.2).
        """
        return self.status in {
            AttachmentStatus.SCANNED,
            AttachmentStatus.EXTRACTING,
            AttachmentStatus.READY,
        } and not self.is_deleted


class AttachmentScan(BaseModel):
    """
    The scan verdict, recorded BEFORE any extraction is attempted.

    Its own table so the ordering is provable. ``scan_before_extract`` is not a comment
    in the pipeline — it is a row that must exist with ``verdict=clean`` before an
    extraction row may be created.
    """

    class Verdict(models.TextChoices):
        CLEAN = "clean", "Clean"
        MALICIOUS = "malicious", "Malicious"
        SUSPICIOUS = "suspicious", "Suspicious"
        ERROR = "error", "Error"

    attachment = models.ForeignKey(
        Attachment, on_delete=models.CASCADE, related_name="scans"
    )
    engine = models.CharField(max_length=64, default="builtin")
    verdict = models.CharField(
        max_length=16, choices=Verdict.choices, default=Verdict.ERROR, db_index=True
    )
    detail = models.TextField(blank=True, default="")
    scanned_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-scanned_at"]
        verbose_name = "Attachment scan"
        verbose_name_plural = "Attachment scans"

    def __str__(self) -> str:
        return f"AttachmentScan({self.attachment_id}: {self.verdict})"

    @property
    def is_clean(self) -> bool:
        return self.verdict == self.Verdict.CLEAN


class AttachmentExtraction(BaseModel):
    """
    Text extracted in the SANDBOX.

    ``text`` is nullable because an OPAQUE format is a valid, successful outcome — the
    file is accepted and represented by metadata only. That is not an error, and §13.4
    of the Playbook is explicit that we must not call it one:

        NEVER CALL AN ACCEPTED FILE A FAILURE. The visitor gave us something; we do not
        tell them it was worthless.
    """

    attachment = models.OneToOneField(
        Attachment, on_delete=models.CASCADE, related_name="extraction"
    )
    handler = models.CharField(max_length=32, default="opaque", db_index=True)
    text = models.TextField(null=True, blank=True)
    page_count = models.PositiveIntegerField(default=0)
    char_count = models.PositiveIntegerField(default=0)
    truncated = models.BooleanField(default=False)
    error = models.TextField(blank=True, default="")
    duration_ms = models.PositiveIntegerField(default=0)
    # True when the handler could not read the format but the file was still accepted.
    metadata_only = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Attachment extraction"
        verbose_name_plural = "Attachment extractions"

    def __str__(self) -> str:
        return f"AttachmentExtraction({self.attachment_id}, {self.handler})"

    @property
    def has_text(self) -> bool:
        return bool(self.text and self.text.strip())


class AttachmentExcerpt(BaseModel):
    """
    A relevance-selected slice of extracted text, ready for the context budget.

    Excerpts rather than whole documents because attachment content enters the context
    at PRIORITY 5 (§2.4) — below the visitor's own current turn. A 200-page PDF that
    displaced the question being asked would be the wrong trade every time.
    """

    attachment = models.ForeignKey(
        Attachment, on_delete=models.CASCADE, related_name="excerpts"
    )
    ordinal = models.PositiveIntegerField(default=0)
    text = models.TextField()
    char_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["attachment", "ordinal"]
        verbose_name = "Attachment excerpt"
        verbose_name_plural = "Attachment excerpts"

    def __str__(self) -> str:
        return f"AttachmentExcerpt({self.attachment_id}#{self.ordinal})"


class AttachmentAuditEntry(BaseModel):
    """
    One audited action on an attachment (§19.7 rule 9).

    A separate table rather than a JSON column on Attachment: audit rows are append-only
    and must survive the attachment being purged. A purge that erased its own audit trail
    would make the retention guarantee unverifiable — which is the same as not having one.
    """

    attachment = models.ForeignKey(
        Attachment, on_delete=models.CASCADE, related_name="audit_entries"
    )
    action = models.CharField(max_length=24, db_index=True)
    plane = models.CharField(max_length=16, blank=True, default="")
    subject = models.CharField(max_length=128, blank=True, default="")
    purpose = models.CharField(max_length=300, blank=True, default="")
    detail = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Attachment audit entry"
        verbose_name_plural = "Attachment audit entries"
        indexes = [models.Index(fields=["attachment", "action"])]

    def __str__(self) -> str:
        return f"AttachmentAudit({self.attachment_id}: {self.action})"
