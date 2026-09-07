"""Production-only structural validation for attachment storage/scanner settings."""

from __future__ import annotations

import shlex
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


def validate_production_attachments(
    *,
    enabled: bool,
    base_dir,
    storage_backend: str,
    configured_blob_root: str,
    s3_bucket: str,
    s3_endpoint: str,
    s3_region: str,
    s3_access_key_id: str,
    s3_secret_access_key: str,
    s3_prefix: str,
    s3_addressing_style: str,
    av_command: str,
    process_inline: bool,
    shared_storage_confirmed: bool = False,
) -> None:
    """Fail startup on structural misconfiguration, without contacting providers."""
    if not enabled:
        return

    backend = (storage_backend or "").strip().lower()
    if backend not in {"filesystem", "s3"}:
        raise ImproperlyConfigured(
            "ENABLE_ATTACHMENTS=true requires ATTACHMENT_STORAGE_BACKEND=filesystem or s3."
        )

    if backend == "filesystem":
        raw_root = (configured_blob_root or "").strip()
        if not raw_root:
            raise ImproperlyConfigured(
                "Filesystem attachment storage requires ATTACHMENT_BLOB_ROOT in production."
            )
        root = Path(raw_root).expanduser()
        if not root.is_absolute():
            raise ImproperlyConfigured("ATTACHMENT_BLOB_ROOT must be an absolute production path.")
        resolved_root = root.resolve(strict=False)
        resolved_base = Path(base_dir).resolve(strict=False)
        try:
            inside_checkout = resolved_root == resolved_base or resolved_root.is_relative_to(
                resolved_base
            )
        except AttributeError:  # pragma: no cover
            inside_checkout = str(resolved_root).startswith(str(resolved_base) + "/")
        if (
            inside_checkout
            or str(resolved_root).startswith("/tmp/")
            or resolved_root == Path("/tmp")
        ):
            raise ImproperlyConfigured(
                "ATTACHMENT_BLOB_ROOT must not use the application checkout or /tmp in production."
            )
    else:
        # Validate only shape at import time. Provider reachability is deliberately a
        # runtime concern tested by validate_attachment_runtime, not by Django settings import.
        required = {
            "ATTACHMENT_S3_BUCKET": s3_bucket,
            "ATTACHMENT_S3_ENDPOINT": s3_endpoint,
            "ATTACHMENT_S3_REGION": s3_region,
            "ATTACHMENT_S3_ACCESS_KEY_ID": s3_access_key_id,
            "ATTACHMENT_S3_SECRET_ACCESS_KEY": s3_secret_access_key,
        }
        missing = [name for name, value in required.items() if not (value or "").strip()]
        if missing:
            raise ImproperlyConfigured(
                "S3 attachment storage is missing required settings: " + ", ".join(missing)
            )
        prefix = (s3_prefix or "").strip()
        if prefix.startswith("/") or ".." in prefix.split("/"):
            raise ImproperlyConfigured("ATTACHMENT_S3_PREFIX must be a safe bucket-relative prefix.")
        addressing = (s3_addressing_style or "auto").strip().lower()
        if addressing not in {"auto", "virtual", "path"}:
            raise ImproperlyConfigured(
                "ATTACHMENT_S3_ADDRESSING_STYLE must be auto, virtual, or path."
            )

    command = (av_command or "").strip()
    if not command:
        raise ImproperlyConfigured(
            "ENABLE_ATTACHMENTS=true in production requires ATTACHMENT_AV_COMMAND."
        )
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise ImproperlyConfigured("ATTACHMENT_AV_COMMAND is not valid argv.") from exc
    if not argv:
        raise ImproperlyConfigured("ATTACHMENT_AV_COMMAND must name an executable.")

    # Inline is today's release architecture. If it is explicitly disabled while using
    # filesystem storage, the worker must be confirmed to see the same durable bytes.
    if backend == "filesystem" and not process_inline and not shared_storage_confirmed:
        raise ImproperlyConfigured(
            "ATTACHMENT_PROCESS_INLINE=false with filesystem storage requires "
            "ATTACHMENT_SHARED_STORAGE_CONFIRMED=true."
        )
