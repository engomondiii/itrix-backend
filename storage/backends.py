"""
Storage backends.

A tiny abstraction over "read these bytes" that works for both local paths and
``s3://`` URIs. The knowledge_core document loader uses ``read_bytes`` so the same
KnowledgeDocument record can point at a local file in dev or an S3 object in prod.

boto3 is imported lazily so the project never requires it unless an s3:// path is
actually read. If boto3 (or credentials) are missing, a clear error is raised.
"""

from __future__ import annotations

import logging
import os

from storage.utils import is_s3_uri, parse_s3_uri

logger = logging.getLogger("itrix")


class StorageError(RuntimeError):
    """Raised when a file cannot be read from the configured backend."""


class LocalStorageBackend:
    """Reads files from the local filesystem (relative paths resolve to BASE_DIR)."""

    def __init__(self, base_dir: str | None = None):
        self.base_dir = base_dir

    def _resolve(self, path: str) -> str:
        if os.path.isabs(path):
            return path
        if self.base_dir:
            return os.path.join(self.base_dir, path)
        return path

    def exists(self, path: str) -> bool:
        return os.path.exists(self._resolve(path))

    def read_bytes(self, path: str) -> bytes:
        resolved = self._resolve(path)
        if not os.path.exists(resolved):
            raise StorageError(f"Local file not found: {resolved}")
        with open(resolved, "rb") as fh:
            return fh.read()


class S3StorageBackend:
    """Reads objects from S3 via boto3 (imported lazily)."""

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            try:
                import boto3  # noqa: PLC0415 - lazy by design
            except ImportError as exc:  # pragma: no cover
                raise StorageError(
                    "boto3 is required to read s3:// paths. Install boto3 or use local paths."
                ) from exc
            self._client = boto3.client("s3")
        return self._client

    def exists(self, uri: str) -> bool:
        bucket, key = parse_s3_uri(uri)
        try:
            self.client.head_object(Bucket=bucket, Key=key)
            return True
        except Exception:  # noqa: BLE001
            return False

    def read_bytes(self, uri: str) -> bytes:
        bucket, key = parse_s3_uri(uri)
        try:
            obj = self.client.get_object(Bucket=bucket, Key=key)
            return obj["Body"].read()
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Could not read {uri}: {exc}") from exc


def get_backend_for(path: str):
    """Return the appropriate backend instance for ``path``."""
    if is_s3_uri(path):
        return S3StorageBackend()
    from django.conf import settings

    return LocalStorageBackend(base_dir=str(getattr(settings, "BASE_DIR", "")))


def read_file_bytes(path: str) -> bytes:
    """Convenience: read a file's bytes from local disk or S3, transparently."""
    backend = get_backend_for(path)
    return backend.read_bytes(path)


def file_exists(path: str) -> bool:
    return get_backend_for(path).exists(path)
