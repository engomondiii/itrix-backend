"""Production-only structural validation for attachment storage/scanner settings."""

from __future__ import annotations

import shlex
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


def _executable_available(name: str) -> bool:
    """Return whether the configured local scanner executable is available.

    Kept behind a tiny seam so unit tests patch the production contract itself rather
    than reaching into Python's ``shutil`` implementation details.
    """
    import shutil

    return shutil.which(name) is not None


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
    """Fail startup on unsafe structure without contacting the storage provider.

    Provider reachability is intentionally a runtime-validation concern. Local runtime
    facts that are safe to verify at import time, such as the configured scanner binary
    being present in the image, are validated here so an attachment-capable production
    process cannot boot with a scanner command it can never execute.
    """
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
        # Shape only: no boto client is created and no provider request is made here.
        required = {
            "ATTACHMENT_S3_BUCKET": s3_bucket,
            "ATTACHMENT_S3_ENDPOINT": s3_endpoint,
            "ATTACHMENT_S3_REGION": s3_region,
            "ATTACHMENT_S3_ACCESS_KEY_ID": s3_access_key_id,
            "ATTACHMENT_S3_SECRET_ACCESS_KEY": s3_secret_access_key,
            "ATTACHMENT_S3_PREFIX": s3_prefix,
        }
        missing = [name for name, value in required.items() if not (value or "").strip()]
        if missing:
            raise ImproperlyConfigured(
                "S3 attachment storage is missing required settings: " + ", ".join(missing)
            )

        bucket = (s3_bucket or "").strip()
        if "/" in bucket or "\\" in bucket or bucket in {".", ".."}:
            raise ImproperlyConfigured("ATTACHMENT_S3_BUCKET must be a bucket name, not a path.")

        endpoint = (s3_endpoint or "").strip().lower()
        if not (endpoint.startswith("https://") or endpoint.startswith("http://")):
            raise ImproperlyConfigured("ATTACHMENT_S3_ENDPOINT must be an http(s) endpoint URL.")

        prefix = (s3_prefix or "").strip()
        parts = prefix.replace("\\", "/").split("/")
        if (
            prefix.startswith("/")
            or "\\" in prefix
            or any(part in {".", ".."} for part in parts)
            or not prefix.endswith("/")
        ):
            raise ImproperlyConfigured(
                "ATTACHMENT_S3_PREFIX must be a safe non-empty bucket-relative prefix ending in '/'."
            )

        addressing = (s3_addressing_style or "").strip().lower()
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
    if not _executable_available(argv[0]):
        raise ImproperlyConfigured(
            "ATTACHMENT_AV_COMMAND executable is not available in the production runtime."
        )

    # A separate process can consume S3 directly. Filesystem mode needs an explicit
    # operator assertion that the worker and web process see the same durable mount.
    if backend == "filesystem" and not process_inline and not shared_storage_confirmed:
        raise ImproperlyConfigured(
            "ATTACHMENT_PROCESS_INLINE=false with filesystem storage requires "
            "ATTACHMENT_SHARED_STORAGE_CONFIRMED=true."
        )
