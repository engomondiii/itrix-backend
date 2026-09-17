"""Safe runtime validation for production attachment storage and malware scanning."""

from __future__ import annotations

import hashlib
import secrets

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from apps.attachments import storage
from apps.attachments.models import AttachmentScan
from apps.attachments.services import scanner


class AttachmentRuntimeValidationError(RuntimeError):
    """The configured attachment runtime could not prove its production contract."""


def validate_attachment_runtime() -> dict:
    """Probe storage and external AV without using customer content.

    The probe is intentionally tiny and synthetic. It proves write/head/read/integrity,
    scans a securely materialized clean sample with the configured AV command, and removes
    the probe object in ``finally``. Secrets and provider credentials never enter the
    returned report.
    """
    if not bool(getattr(settings, "ENABLE_ATTACHMENTS", False)):
        return {"enabled": False, "validated": True}

    command = str(getattr(settings, "ATTACHMENT_AV_COMMAND", "") or "").strip()
    if not command:
        raise ImproperlyConfigured(
            "ENABLE_ATTACHMENTS=true requires ATTACHMENT_AV_COMMAND before runtime validation."
        )

    payload = b"itriX attachment runtime validation probe\n" + secrets.token_bytes(32)
    expected_hash = hashlib.sha256(payload).hexdigest()
    key = storage.new_blob_key("runtime-probe.txt")
    wrote = False
    failure: Exception | None = None

    try:
        written, stored_hash = storage.write(key, payload)
        wrote = True
        if written != len(payload) or stored_hash != expected_hash:
            raise AttachmentRuntimeValidationError("storage write integrity metadata mismatch")

        if not storage.exists(key):
            raise AttachmentRuntimeValidationError("storage head check could not find probe object")

        recovered = storage.read(key)
        recovered_hash = hashlib.sha256(recovered).hexdigest()
        if recovered != payload or recovered_hash != expected_hash:
            raise AttachmentRuntimeValidationError("storage read integrity mismatch")

        with storage.materialize(key) as path:
            verdict = scanner._external_av(str(path))
        if verdict is None:
            raise AttachmentRuntimeValidationError("external malware scanner did not run")
        av_verdict, av_detail = verdict
        if av_verdict != AttachmentScan.Verdict.CLEAN:
            detail = (av_detail or "").strip()[:200]
            raise AttachmentRuntimeValidationError(
                f"clean malware-scan probe did not pass ({av_verdict}): {detail}"
            )
    except Exception as exc:  # noqa: BLE001
        failure = exc
    finally:
        if wrote:
            try:
                deleted = storage.delete(key)
                still_exists = storage.exists(key) if deleted else True
            except Exception as cleanup_exc:  # noqa: BLE001
                raise AttachmentRuntimeValidationError(
                    "attachment runtime probe cleanup failed"
                ) from cleanup_exc
            if not deleted or still_exists:
                raise AttachmentRuntimeValidationError(
                    "attachment runtime probe object was not durably deleted"
                )

    if failure is not None:
        raise failure

    return {
        "enabled": True,
        "validated": True,
        "storage_backend": storage.backend_name(),
        "write_read_integrity": True,
        "malware_scan": "clean",
        "probe_deleted": True,
    }
