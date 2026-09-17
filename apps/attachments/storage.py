"""Private provider-independent attachment blob storage.

The public API intentionally exposes no URL.  Callers use opaque blob keys and this
module routes them to either the local filesystem (development/tests) or a private
S3-compatible bucket (production).  S3 objects are never written with a public ACL.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger("itrix")
_CHUNK = 1024 * 1024


def backend_name() -> str:
    value = str(getattr(settings, "ATTACHMENT_STORAGE_BACKEND", "filesystem") or "filesystem")
    value = value.strip().lower()
    if value not in {"filesystem", "s3"}:
        raise ImproperlyConfigured("ATTACHMENT_STORAGE_BACKEND must be filesystem or s3.")
    return value


def blob_root() -> Path:
    """Filesystem root. Deliberately unavailable in S3 mode."""
    if backend_name() != "filesystem":
        raise ImproperlyConfigured("ATTACHMENT_BLOB_ROOT is not used by the S3 backend.")
    configured = getattr(settings, "ATTACHMENT_BLOB_ROOT", "")
    if configured:
        return Path(configured)
    return Path(settings.BASE_DIR) / "private_blobs" / "attachments"


def new_blob_key(filename: str = "") -> str:
    """Return an opaque key; the visitor filename is never part of the object path."""
    suffix = ""
    if "." in (filename or ""):
        raw = filename.rsplit(".", 1)[-1][:12]
        cleaned = "".join(ch for ch in raw if ch.isalnum())
        if cleaned:
            suffix = f".{cleaned.lower()}"
    return f"{uuid.uuid4().hex}{suffix}"


def _validate_blob_key(blob_key: str) -> str:
    key = str(blob_key or "")
    # Keys written by this module are a single opaque path component. Keep reads just as
    # strict in case a database row was ever corrupted or written by old code.
    if not key or key in {".", ".."} or "/" in key or "\\" in key or "\x00" in key:
        raise ValueError(f"Invalid attachment blob key: {key!r}")
    return key


def _path_for(blob_key: str) -> Path:
    key = _validate_blob_key(blob_key)
    root = blob_root().resolve()
    candidate = (root / key).resolve()
    try:
        inside = candidate.is_relative_to(root)
    except AttributeError:  # pragma: no cover
        inside = str(candidate).startswith(str(root) + os.sep)
    if not inside:
        raise ValueError(f"Refusing to resolve a blob key outside the root: {blob_key!r}")
    return candidate


def _s3_key(blob_key: str) -> str:
    key = _validate_blob_key(blob_key)
    prefix = str(getattr(settings, "ATTACHMENT_S3_PREFIX", "attachments/") or "").strip()
    prefix = prefix.strip("/")
    return f"{prefix}/{key}" if prefix else key


def _s3_client():
    import boto3
    from botocore.config import Config

    bucket = str(getattr(settings, "ATTACHMENT_S3_BUCKET", "") or "").strip()
    if not bucket:
        raise ImproperlyConfigured("ATTACHMENT_S3_BUCKET is required for S3 attachment storage.")
    addressing = str(
        getattr(settings, "ATTACHMENT_S3_ADDRESSING_STYLE", "auto") or "auto"
    ).strip().lower()
    if addressing not in {"auto", "virtual", "path"}:
        raise ImproperlyConfigured(
            "ATTACHMENT_S3_ADDRESSING_STYLE must be auto, virtual, or path."
        )
    return boto3.client(
        "s3",
        endpoint_url=(str(getattr(settings, "ATTACHMENT_S3_ENDPOINT", "") or "").strip() or None),
        region_name=(str(getattr(settings, "ATTACHMENT_S3_REGION", "") or "").strip() or None),
        aws_access_key_id=(
            str(getattr(settings, "ATTACHMENT_S3_ACCESS_KEY_ID", "") or "").strip() or None
        ),
        aws_secret_access_key=(
            str(getattr(settings, "ATTACHMENT_S3_SECRET_ACCESS_KEY", "") or "").strip() or None
        ),
        config=Config(s3={"addressing_style": addressing}),
    )


def _bucket() -> str:
    return str(getattr(settings, "ATTACHMENT_S3_BUCKET", "") or "").strip()


def write(blob_key: str, data: bytes) -> tuple[int, str]:
    payload = data or b""
    digest = hashlib.sha256(payload).hexdigest()
    if backend_name() == "s3":
        _s3_client().put_object(
            Bucket=_bucket(),
            Key=_s3_key(blob_key),
            Body=payload,
            ContentType="application/octet-stream",
        )
        return len(payload), digest

    path = _path_for(blob_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return len(payload), digest


def write_stream(blob_key: str, chunks) -> tuple[int, str]:
    """Write a stream without exposing a provider-specific path to callers."""
    if backend_name() == "filesystem":
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

    digest = hashlib.sha256()
    size = 0
    with tempfile.SpooledTemporaryFile(max_size=8 * _CHUNK, mode="w+b") as handle:
        for chunk in chunks:
            handle.write(chunk)
            digest.update(chunk)
            size += len(chunk)
        handle.seek(0)
        _s3_client().put_object(
            Bucket=_bucket(),
            Key=_s3_key(blob_key),
            Body=handle,
            ContentType="application/octet-stream",
        )
    return size, digest.hexdigest()


def iter_chunks(blob_key: str, chunk_size: int = _CHUNK):
    """Yield private object bytes and close the underlying handle deterministically."""
    if backend_name() == "filesystem":
        with _path_for(blob_key).open("rb") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                yield chunk
        return

    response = _s3_client().get_object(Bucket=_bucket(), Key=_s3_key(blob_key))
    body = response["Body"]
    try:
        while True:
            chunk = body.read(chunk_size)
            if not chunk:
                break
            yield chunk
    finally:
        body.close()


def read(blob_key: str) -> bytes:
    return b"".join(iter_chunks(blob_key))


def exists(blob_key: str) -> bool:
    if backend_name() == "filesystem":
        try:
            return _path_for(blob_key).exists()
        except ValueError:
            return False
    from botocore.exceptions import ClientError

    try:
        _s3_client().head_object(Bucket=_bucket(), Key=_s3_key(blob_key))
        return True
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
            return False
        raise


def delete(blob_key: str) -> bool:
    """Idempotently remove an object; provider failures are reported as False."""
    try:
        if backend_name() == "s3":
            _s3_client().delete_object(Bucket=_bucket(), Key=_s3_key(blob_key))
            return True
        path = _path_for(blob_key)
        if path.exists():
            path.unlink()
        return True
    except (OSError, ValueError, Exception) as exc:  # noqa: BLE001
        # Intentionally fail the operation rather than claiming a confidential blob is gone.
        logger.exception("could not delete attachment blob %s: %s", blob_key, exc)
        return False


@contextmanager
def materialize(blob_key: str):
    """Securely materialize canonical bytes for tools (such as ClamAV) needing a path."""
    fd, raw_path = tempfile.mkstemp(prefix="itrix-attachment-", suffix=".scan")
    path = Path(raw_path)
    try:
        try:
            os.fchmod(fd, 0o600)
        except OSError:
            pass
        with os.fdopen(fd, "wb") as handle:
            for chunk in iter_chunks(blob_key):
                handle.write(chunk)
        yield path
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.exception("could not remove attachment scan temporary file")


def purge_all() -> int:
    """Remove all blobs under only this application's attachment prefix."""
    if backend_name() == "filesystem":
        root = blob_root()
        if not root.exists():
            return 0
        count = sum(1 for item in root.rglob("*") if item.is_file())
        shutil.rmtree(root, ignore_errors=True)
        return count

    client = _s3_client()
    prefix = str(getattr(settings, "ATTACHMENT_S3_PREFIX", "attachments/") or "").strip("/")
    prefix = f"{prefix}/" if prefix else ""
    count = 0
    token = None
    while True:
        kwargs = {"Bucket": _bucket(), "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        page = client.list_objects_v2(**kwargs)
        for item in page.get("Contents", []):
            key = item.get("Key")
            if key:
                client.delete_object(Bucket=_bucket(), Key=key)
                count += 1
        if not page.get("IsTruncated"):
            break
        token = page.get("NextContinuationToken")
    return count
