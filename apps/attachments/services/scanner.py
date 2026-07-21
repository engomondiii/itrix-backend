"""
Scan BEFORE extraction (Backend v6.0 §4.3, §19.7 rule 3).

    Every attachment passes an antivirus/malware scan and an archive-bomb check BEFORE
    any extraction is attempted.

── WHY THE ORDER IS THE WHOLE POINT ─────────────────────────────────────────
Extraction is where we hand attacker-controlled bytes to a parser. Parsers are where
memory-corruption bugs live. Scanning afterwards would mean the dangerous step had
already run.

``scan()`` writes an ``AttachmentScan`` row, and ``extractor.run()`` REFUSES to proceed
without a clean one. The ordering is therefore enforced by data, not by the two functions
happening to be called in the right sequence.

── WHAT THIS SCANNER IS AND IS NOT ──────────────────────────────────────────
The built-in engine does type sniffing, archive-bomb detection and a signature check for
a few unambiguous cases. It is NOT a substitute for ClamAV. When ``ATTACHMENT_AV_COMMAND``
is configured we shell out to a real scanner and use its verdict; when it is not, we run
the built-in checks and mark the engine honestly as ``builtin`` so nobody reads a clean
verdict as more than it is.
"""

from __future__ import annotations

import logging
import subprocess
import zipfile
from io import BytesIO

from django.conf import settings

from apps.attachments import policy
from apps.attachments.models import AttachmentScan, AttachmentStatus

logger = logging.getLogger("itrix")

# Magic-number sniffing. The DECLARED mime is attacker-controlled; this is not.
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

# Types that are never useful as a document and are treated as suspicious on sight.
_EXECUTABLE_MIMES = {"application/x-executable", "application/x-msdownload"}

# OOXML containers are zips; their inner type is decided by the entry names.
_OOXML_MARKERS = {
    "word/": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xl/": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt/": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def detect_mime(data: bytes, filename: str = "") -> str:
    """Sniff the real type from the bytes, never from the declared value."""
    head = data[:512]
    for signature, mime in _MAGIC:
        if head.startswith(signature):
            if mime == "application/zip":
                return _refine_zip(data)
            return mime
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
        printable = sum(1 for b in head if 9 <= b <= 13 or 32 <= b <= 126)
        return printable / max(len(head), 1) > 0.85


def check_archive_bomb(data: bytes) -> tuple[bool, str]:
    """
    Detect decompression bombs. Returns ``(is_bomb, detail)``.

    Three independent limits, because a bomb only needs to defeat one of them:
    total expansion RATIO, nesting DEPTH, and ENTRY COUNT. A 42-byte zip that expands to
    4.5 PB fails on ratio; a zip-of-zips fails on depth; a zip with a million empty files
    fails on count.
    """
    if not data[:4].startswith(b"PK"):
        return False, ""
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > policy.MAX_ARCHIVE_ENTRIES:
                return True, f"{len(infos)} entries exceeds {policy.MAX_ARCHIVE_ENTRIES}"

            compressed = sum(i.compress_size for i in infos) or 1
            uncompressed = sum(i.file_size for i in infos)
            ratio = uncompressed / compressed
            if ratio > policy.MAX_ARCHIVE_RATIO:
                return True, f"expansion ratio {ratio:.0f}x exceeds {policy.MAX_ARCHIVE_RATIO}x"

            for info in infos:
                depth = info.filename.count("/")
                if depth > policy.MAX_ARCHIVE_DEPTH:
                    return True, f"nesting depth {depth} exceeds {policy.MAX_ARCHIVE_DEPTH}"
                # A nested archive is where depth-based bombs hide.
                if info.filename.lower().endswith((".zip", ".gz", ".bz2", ".xz", ".7z")):
                    if info.file_size > policy.max_attachment_bytes():
                        return True, "nested archive larger than the per-file limit"
    except zipfile.BadZipFile:
        return False, ""
    except Exception as exc:  # noqa: BLE001
        return True, f"unreadable archive: {exc}"
    return False, ""


def _external_av(blob_path: str) -> tuple[str, str] | None:
    """
    Run a configured external scanner. Returns ``(verdict, detail)`` or None.

    Configured via ``ATTACHMENT_AV_COMMAND``, e.g. ``clamdscan --no-summary``. The path
    is appended as the final argument. A non-zero exit that is not 1 is reported as
    ERROR rather than clean — a scanner we could not run has told us nothing.
    """
    command = getattr(settings, "ATTACHMENT_AV_COMMAND", "") or ""
    if not command:
        return None
    try:
        argv = command.split() + [blob_path]
        result = subprocess.run(argv, capture_output=True, timeout=60, check=False)
        output = (result.stdout or b"").decode(errors="replace")[:500]
        if result.returncode == 0:
            return AttachmentScan.Verdict.CLEAN, output
        if result.returncode == 1:
            return AttachmentScan.Verdict.MALICIOUS, output
        return AttachmentScan.Verdict.ERROR, f"exit {result.returncode}: {output}"
    except subprocess.TimeoutExpired:
        return AttachmentScan.Verdict.ERROR, "scanner timed out"
    except Exception as exc:  # noqa: BLE001
        return AttachmentScan.Verdict.ERROR, f"scanner failed: {exc}"


def scan(attachment) -> AttachmentScan:
    """
    Scan one attachment and record the verdict.

    ALWAYS writes a row, even on error. A missing scan row is indistinguishable from a
    scan that was skipped, and the extractor treats both the same way — it refuses.
    """
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

    # A declared type that disagrees with the bytes is a signal worth keeping.
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

    external = _external_av(str(_blob_path(attachment)))
    if external is not None:
        engine = getattr(settings, "ATTACHMENT_AV_COMMAND", "av").split()[0]
        ext_verdict, ext_detail = external
        details.append(ext_detail)
        # The external verdict can only make things WORSE, never better. A built-in
        # detection of an archive bomb is not overturned by a clean AV pass.
        if ext_verdict != AttachmentScan.Verdict.CLEAN:
            verdict = ext_verdict
            risk_flags.append(f"av:{ext_verdict}")

    record = AttachmentScan.objects.create(
        attachment=attachment,
        engine=engine,
        verdict=verdict,
        detail=" | ".join(d for d in details if d)[:2000],
    )
    _apply(attachment, record, risk_flags)
    return record


def _blob_path(attachment):
    from apps.attachments import storage

    return storage.blob_root() / attachment.blob_key


def _apply(attachment, record: AttachmentScan, risk_flags: list[str]) -> None:
    """Move the attachment to its post-scan status and record internal risk flags."""
    flags = list(attachment.risk_flags or [])
    for flag in risk_flags:
        if flag not in flags:
            flags.append(flag)
    attachment.risk_flags = flags

    if record.verdict == AttachmentScan.Verdict.CLEAN:
        attachment.status = AttachmentStatus.SCANNED
    else:
        # Quarantine covers malicious, suspicious AND error. An unscannable file is not
        # a safe file — treating "we could not tell" as clean is how scanners get bypassed.
        attachment.status = AttachmentStatus.QUARANTINED
        attachment.visitor_note = policy.MSG_COULD_NOT_PROCESS
        _notify_quarantine(attachment, record)

    attachment.save(
        update_fields=["status", "risk_flags", "detected_mime", "visitor_note", "updated_at"]
    )


def _notify_quarantine(attachment, record) -> None:
    """Tell the team plane. Best-effort — never blocks the visitor's turn."""
    try:
        from apps.notifications.services.notification_creator import notify_attachment_quarantine

        notify_attachment_quarantine(attachment, record)
    except Exception:  # noqa: BLE001
        logger.debug("quarantine notification skipped (notifier unavailable)")


def has_clean_scan(attachment) -> bool:
    """
    The gate the extractor consults.

    Requires an actual CLEAN row. Absence of a malicious row is not the same thing.
    """
    return AttachmentScan.objects.filter(
        attachment=attachment, verdict=AttachmentScan.Verdict.CLEAN
    ).exists()
