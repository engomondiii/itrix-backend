"""
Storage utilities.

Pure helpers used by the knowledge_core ingestion flow and the admin upload path:

* ``compute_file_hash`` — stable SHA-256 of a file's bytes (dedupe / change detection).
* ``safe_filename``     — sanitises an arbitrary filename for safe disk/S3 storage.
* ``knowledge_doc_upload_path`` — Django ``upload_to`` callable that organises runtime
  admin uploads under ``knowledge_documents/<doc-slug>/<safe-filename>`` (MEDIA_ROOT).

None of these import Django models, so they're safe to use anywhere.
"""

from __future__ import annotations

import hashlib
import os

from slugify import slugify


def compute_file_hash(source, *, chunk_size: int = 65536) -> str:
    """
    Return the SHA-256 hex digest of ``source``.

    ``source`` may be a filesystem path (str/os.PathLike) or a readable binary
    file-like object (it will be read and, if seekable, rewound afterwards).
    """
    digest = hashlib.sha256()

    if hasattr(source, "read"):
        pos = source.tell() if hasattr(source, "tell") else None
        for chunk in iter(lambda: source.read(chunk_size), b""):
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8")
            digest.update(chunk)
        if pos is not None and hasattr(source, "seek"):
            source.seek(pos)
        return digest.hexdigest()

    with open(source, "rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_filename(filename: str) -> str:
    """
    Sanitise a filename: keep the extension, slugify the stem, avoid empties.

    e.g. ``"ALPHA Benchmark Results (v2).docx"`` -> ``"alpha-benchmark-results-v2.docx"``
    """
    filename = os.path.basename(filename or "").strip()
    stem, ext = os.path.splitext(filename)
    ext = ext.lower().lstrip(".")
    slug = slugify(stem) or "document"
    return f"{slug}.{ext}" if ext else slug


def knowledge_doc_upload_path(instance, filename: str) -> str:
    """
    Django ``upload_to`` callable for KnowledgeDocument runtime uploads.

    Produces ``knowledge_documents/<doc-slug>/<safe-filename>``. ``instance`` is the
    KnowledgeDocument; we prefer its title for the folder slug, falling back to its id.
    """
    title = getattr(instance, "title", "") or getattr(instance, "namespace", "") or "doc"
    folder = slugify(title) or "doc"
    # Disambiguate with a short id fragment so same-titled docs don't collide.
    pk = getattr(instance, "id", None)
    if pk:
        folder = f"{folder}-{str(pk)[:8]}"
    return f"knowledge_documents/{folder}/{safe_filename(filename)}"


def is_s3_uri(path: str) -> bool:
    return bool(path) and path.lower().startswith("s3://")


def parse_s3_uri(uri: str) -> tuple[str, str]:
    """Split ``s3://bucket/key/parts`` into ``("bucket", "key/parts")``."""
    if not is_s3_uri(uri):
        raise ValueError(f"Not an s3:// URI: {uri!r}")
    without_scheme = uri[len("s3://") :]
    bucket, _, key = without_scheme.partition("/")
    return bucket, key
