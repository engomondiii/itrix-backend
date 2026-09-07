"""Production-only validation for the attachment storage/scanner contract."""

from __future__ import annotations

import shlex
import shutil
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


def validate_production_attachments(
    *,
    enabled: bool,
    base_dir,
    configured_blob_root: str,
    av_command: str,
    process_inline: bool,
    shared_storage_confirmed: bool = False,
) -> None:
    """Fail startup rather than expose an attachment feature with an unsafe runtime.

    The current implementation stores bytes on a filesystem. Production therefore needs
    an operator-selected durable mount, not the repository-local default. A real external
    scanner is required because the built-in type/archive checks explicitly are not an AV
    substitute. A separate worker may process files only after the operator confirms that
    the same blob path is visible to both services.
    """
    if not enabled:
        return

    raw_root = (configured_blob_root or "").strip()
    if not raw_root:
        raise ImproperlyConfigured(
            "ENABLE_ATTACHMENTS=true requires ATTACHMENT_BLOB_ROOT to point at a durable "
            "production volume outside the application checkout."
        )

    root = Path(raw_root).expanduser()
    if not root.is_absolute():
        raise ImproperlyConfigured("ATTACHMENT_BLOB_ROOT must be an absolute production path.")

    resolved_root = root.resolve(strict=False)
    resolved_base = Path(base_dir).resolve(strict=False)
    try:
        inside_checkout = resolved_root == resolved_base or resolved_root.is_relative_to(resolved_base)
    except AttributeError:  # pragma: no cover - Python < 3.9 compatibility
        inside_checkout = str(resolved_root).startswith(str(resolved_base) + "/")
    if inside_checkout or str(resolved_root).startswith("/tmp/") or resolved_root == Path("/tmp"):
        raise ImproperlyConfigured(
            "ATTACHMENT_BLOB_ROOT must not use the application checkout or /tmp in production; "
            "mount durable storage and point the setting there."
        )

    command = (av_command or "").strip()
    if not command:
        raise ImproperlyConfigured(
            "ENABLE_ATTACHMENTS=true in production requires ATTACHMENT_AV_COMMAND for an "
            "external malware scanner."
        )
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise ImproperlyConfigured("ATTACHMENT_AV_COMMAND is not valid shell-style argv.") from exc
    if not argv:
        raise ImproperlyConfigured("ATTACHMENT_AV_COMMAND must name an executable.")
    executable = argv[0]
    if shutil.which(executable) is None:
        raise ImproperlyConfigured(
            "ATTACHMENT_AV_COMMAND executable is not available in the production runtime."
        )

    if not process_inline and not shared_storage_confirmed:
        raise ImproperlyConfigured(
            "ATTACHMENT_PROCESS_INLINE=false requires ATTACHMENT_SHARED_STORAGE_CONFIRMED=true; "
            "the worker must see the same ATTACHMENT_BLOB_ROOT bytes as the web service."
        )
