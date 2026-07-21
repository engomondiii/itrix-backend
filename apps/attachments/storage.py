"""
Blob storage OUTSIDE the web root (Backend v6.0 §4.4, §19.7 rule 2).

    No uploaded file is ever executed, interpreted, or rendered inline as HTML or SVG.

Three properties, and each closes a specific attack:

1. STORED OUTSIDE THE WEB ROOT. A file under a served directory can be fetched directly,
   bypassing every authorization check the download endpoint performs.

2. OPAQUE KEYS. The stored name is derived from a uuid, never from the visitor's
   filename. A filename is attacker-controlled: "../../settings.py" and
   "payload.html" are both filenames.

3. NO PUBLIC URL EXISTS. There is no ``url()`` method on this module. Downloads go
   through a signed, short-lived, authorization-checked endpoint.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import uuid
from pathlib import Path

from django.conf import settings

logger = logging.getLogger("itrix")


def blob_root() -> Path:
    """
    The blob directory. Defaults OUTSIDE MEDIA_ROOT.

    MEDIA_ROOT is served in many deployments. Defaulting there would make every upload
    publicly fetchable the moment somebody enabled media serving.
    """
    configured = getattr(settings, "ATTACHMENT_BLOB_ROOT", "")
    if configured:
        return Path(configured)
    return Path(settings.BASE_DIR) / "private_blobs" / "attachments"


def new_blob_key(filename: str = "") -> str:
    """
    An opaque storage key.

    The visitor's filename is preserved on the MODEL for display, and deliberately not
    used here. Only the extension is carried across, and only after being stripped of
    anything that is not alphanumeric.
    """
    suffix = ""
    if "." in (filename or ""):
        raw = filename.rsplit(".", 1)[-1][:12]
        cleaned = "".join(ch for ch in raw if ch.isalnum())
        if cleaned:
            suffix = f".{cleaned.lower()}"
    return f"{uuid.uuid4().hex}{suffix}"


def _path_for(blob_key: str) -> Path:
    """
    Resolve a key to a path, refusing anything that escapes the root.

    The traversal check is not theatre: ``blob_key`` reaches here from a database row,
    and a row is only as trustworthy as everything that has ever written to it.
    """
    root = blob_root().resolve()
    candidate = (root / blob_key).resolve()
    if not str(candidate).startswith(str(root)):
        raise ValueError(f"Refusing to resolve a blob key outside the root: {blob_key!r}")
    return candidate


def write(blob_key: str, data: bytes) -> tuple[int, str]:
    """Write bytes. Returns ``(size, sha256)``."""
    path = _path_for(blob_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    # Restrictive mode: readable only by the process that owns it.
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return len(data), hashlib.sha256(data).hexdigest()


def write_stream(blob_key: str, chunks) -> tuple[int, str]:
    """Stream to disk without holding the whole file in memory."""
    path = _path_for(blob_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    with path.open("wb") as handle:
        for chunk in chunks:
            handle.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return size, digest.hexdigest()


def read(blob_key: str) -> bytes:
    return _path_for(blob_key).read_bytes()


def exists(blob_key: str) -> bool:
    try:
        return _path_for(blob_key).exists()
    except ValueError:
        return False


def delete(blob_key: str) -> bool:
    """
    Remove the bytes. Returns True when they are gone.

    Idempotent: a key that is already absent returns True, because the caller's
    intent — "this must not exist" — is satisfied.
    """
    try:
        path = _path_for(blob_key)
    except ValueError:
        return False
    try:
        if path.exists():
            path.unlink()
        return True
    except OSError:
        logger.exception("could not delete blob %s", blob_key)
        return False


def purge_all() -> int:
    """Remove the entire blob tree. Test and operator use only."""
    root = blob_root()
    if not root.exists():
        return 0
    count = sum(1 for _ in root.rglob("*") if _.is_file())
    shutil.rmtree(root, ignore_errors=True)
    return count
