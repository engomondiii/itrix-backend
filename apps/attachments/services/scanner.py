"""Attachment malware scanning. A clean scan is mandatory before extraction."""

from __future__ import annotations

import logging
import shlex
import subprocess
import zipfile
from io import BytesIO

from django.conf import settings

from apps.attachments import policy
from apps.attachments.models import AttachmentScan, AttachmentStatus

logger = logging.getLogger("itrix")

_MAGIC = [
    (b"%PDF-", "application/pdf"),
    (b"PK\x03\x04", "application/zip"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"\x1f\x8b", "application/gzip"),
    (b"BZh", "application/x-bzip2"),
    (b"\xfd7zXZ", "application/x-xz"),
    (b"7z\xbc\xaf\x27\x1c", "application/x-7z-compressed"),
    (b"Rar!\x1a\x07", "application/vnd.rar"),
    (b"\xd0\xcf\x11\xe0", "application/vnd.ms-office"),
    (b"\x7fELF", "application/x-executable"),
    (b"MZ", "application/x-msdownload"),
]
_EXECUTABLE_MIMES = {"application/x-executable", "application/x-msdownload"}
_OOXML_MARKERS = {
    "word/": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xl/": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt/": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def detect_mime(data: bytes, filename: str = "") -> str:
    head = data[:512]
    for signature, mime in _MAGIC:
        if head.startswith(signature):
            return _refine_zip(data) if mime == "application/zip" else mime
    if _looks_like_text(head):
        return "text/plain"
    return "application/octet-stream"


def _refine_zip(data: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = archive.namelist()[:50]
            for marker, mime in _OOXML_MARKERS.items():
                if any(name.startswith(marker) for name in names):
                    return mime
    except Exception:  # noqa: BLE001
        pass
    return "application/zip"


def _looks_like_text(head: bytes) -> bool:
    if not head:
        return True
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
        return True
    except UnicodeDecodeError:
        printable = sum(1 for byte in head if 9 <= byte <= 13 or 32 <= byte <= 126)
        return printable / max(len(head), 1) > 0.85


def check_archive_bomb(data: bytes) -> tuple[bool, str]:
    if not data[:4].startswith(b"PK"):
        return False, ""
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > policy.MAX_ARCHIVE_ENTRIES:
                return True, f"{len(infos)} entries exceeds {policy.MAX_ARCHIVE_ENTRIES}"
            compressed = sum(item.compress_size for item in infos) or 1
            uncompressed = sum(item.file_size for item in infos)
            ratio = uncompressed / compressed
            if ratio > policy.MAX_ARCHIVE_RATIO:
                return True, f"expansion ratio {ratio:.0f}x exceeds {policy.MAX_ARCHIVE_RATIO}x"
            for item in infos:
                depth = item.filename.count("/")
                if depth > policy.MAX_ARCHIVE_DEPTH:
                    return True, f"nesting depth {depth} exceeds {policy.MAX_ARCHIVE_DEPTH}"
                if item.filename.lower().endswith((".zip", ".gz", ".bz2", ".xz", ".7z")):
                    if item.file_size > policy.max_attachment_bytes():
                        return True, "nested archive larger than the per-file limit"
    except zipfile.BadZipFile:
        return False, ""
    except Exception as exc:  # noqa: BLE001
        return True, f"unreadable archive: {exc}"
    return False, ""


def _external_av(blob_path: str) -> tuple[str, str] | None:
    """Run configured AV without a shell. 0=clean, 1=malicious, anything else=error."""
    command = str(getattr(settings, "ATTACHMENT_AV_COMMAND", "") or "").strip()
    if not command:
        return None
    try:
        argv = shlex.split(command)
        if not argv:
            return AttachmentScan.Verdict.ERROR, "scanner command is empty"
        result = subprocess.run(
            [*argv, blob_path],
            capture_output=True,
            timeout=60,
            check=False,
            shell=False,
        )
        output = b"\n".join(part for part in (result.stdout, result.stderr) if part)
        detail = output.decode(errors="replace")[:500]
        if result.returncode == 0:
            return AttachmentScan.Verdict.CLEAN, detail
        if result.returncode == 1:
            return AttachmentScan.Verdict.MALICIOUS, detail
        return AttachmentScan.Verdict.ERROR, f"exit {result.returncode}: {detail}"
    except subprocess.TimeoutExpired:
        return AttachmentScan.Verdict.ERROR, "scanner timed out"
    except Exception as exc:  # noqa: BLE001
        return AttachmentScan.Verdict.ERROR, f"scanner failed: {exc}"


def scan(attachment) -> AttachmentScan:
    """Run built-in safety checks and, when configured, external AV before extraction."""
    from apps.attachments import storage

    attachment.status = AttachmentStatus.SCANNING
    attachment.save(update_fields=["status", "updated_at"])
    engine = "builtin"
    verdict = AttachmentScan.Verdict.CLEAN
    details: list[str] = []
    risk_flags: list[str] = []

    try:
        data = storage.read(attachment.blob_key)
    except Exception as exc:  # noqa: BLE001
        record = AttachmentScan.objects.create(
            attachment=attachment,
            engine=engine,
            verdict=AttachmentScan.Verdict.ERROR,
            detail=f"could not read blob: {exc}",
        )
        _apply(attachment, record, ["blob_unreadable"])
        return record

    detected = detect_mime(data, attachment.filename)
    if detected != attachment.detected_mime:
        attachment.detected_mime = detected
    declared = (attachment.declared_mime or "").lower()
    if declared and detected != "application/octet-stream" and declared != detected:
        risk_flags.append(f"mime_mismatch:{declared}->{detected}")

    if detected in _EXECUTABLE_MIMES:
        verdict = AttachmentScan.Verdict.SUSPICIOUS
        details.append(f"executable content detected ({detected})")
        risk_flags.append("executable")

    is_bomb, bomb_detail = check_archive_bomb(data)
    if is_bomb:
        verdict = AttachmentScan.Verdict.MALICIOUS
        details.append(f"archive bomb: {bomb_detail}")
        risk_flags.append("archive_bomb")

    if str(getattr(settings, "ATTACHMENT_AV_COMMAND", "") or "").strip():
        try:
            # Canonical storage stays private. A random 0600 temp path exists only for
            # scanners that require a pathname and is deleted in storage.materialize's finally.
            with storage.materialize(attachment.blob_key) as blob_path:
                external = _external_av(str(blob_path))
        except Exception as exc:  # noqa: BLE001
            external = (AttachmentScan.Verdict.ERROR, f"scanner materialization failed: {exc}")
        engine = shlex.split(str(getattr(settings, "ATTACHMENT_AV_COMMAND", "av")))[0]
        if external is not None:
            ext_verdict, ext_detail = external
            if ext_detail:
                details.append(ext_detail)
            # An external result may only strengthen a built-in finding. In particular,
            # an AV CLEAN can never erase an executable/archive-bomb finding, and an AV
            # ERROR cannot downgrade a definite built-in malicious/suspicious verdict.
            if ext_verdict == AttachmentScan.Verdict.MALICIOUS:
                verdict = AttachmentScan.Verdict.MALICIOUS
                risk_flags.append("av:malicious")
            elif ext_verdict == AttachmentScan.Verdict.ERROR and verdict == AttachmentScan.Verdict.CLEAN:
                verdict = AttachmentScan.Verdict.ERROR
                risk_flags.append("av:error")

    record = AttachmentScan.objects.create(
        attachment=attachment,
        engine=engine,
        verdict=verdict,
        detail=" | ".join(item for item in details if item)[:2000],
    )
    _apply(attachment, record, risk_flags)
    return record


def _apply(attachment, record: AttachmentScan, risk_flags: list[str]) -> None:
    flags = list(attachment.risk_flags or [])
    for flag in risk_flags:
        if flag not in flags:
            flags.append(flag)
    attachment.risk_flags = flags
    if record.verdict == AttachmentScan.Verdict.CLEAN:
        attachment.status = AttachmentStatus.SCANNED
    else:
        attachment.status = AttachmentStatus.QUARANTINED
        attachment.visitor_note = policy.MSG_COULD_NOT_PROCESS
        _notify_quarantine(attachment, record)
    attachment.save(
        update_fields=["status", "risk_flags", "detected_mime", "visitor_note", "updated_at"]
    )


def _notify_quarantine(attachment, record) -> None:
    try:
        from apps.notifications.services.notification_creator import notify_attachment_quarantine
        notify_attachment_quarantine(attachment, record)
    except Exception:  # noqa: BLE001
        logger.debug("quarantine notification skipped (notifier unavailable)")


def has_clean_scan(attachment) -> bool:
    return AttachmentScan.objects.filter(
        attachment=attachment, verdict=AttachmentScan.Verdict.CLEAN
    ).exists()
