"""
Pinecone upserter.

Upserts chunk vectors (with metadata) into the configured Pinecone index/namespace when
``ENABLE_AI_ENGINE`` is on and a key is present. When disabled, it **no-ops gracefully**
(logging what it would have upserted) so ingestion still completes and marks chunks with
vector ids — the records exist, only the remote upsert is skipped until keys are live.

The Pinecone client is imported lazily.
"""

from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger("itrix")


class PineconeUpsertError(RuntimeError):
    """Remote Pinecone persistence did not complete."""


class PineconeUpserter:
    def __init__(self):
        self.enabled = settings.ENABLE_AI_ENGINE and bool(settings.PINECONE_API_KEY)
        self._index = None

    @property
    def index(self):
        if self._index is None:
            from pinecone import Pinecone  # noqa: PLC0415 - lazy

            pc = Pinecone(api_key=settings.PINECONE_API_KEY)
            self._index = pc.Index(settings.PINECONE_INDEX)
        return self._index

    def upsert(self, *, namespace: str, vectors: list[dict]) -> int:
        """
        Upsert vectors into a namespace.

        ``vectors`` is a list of ``{"id", "values", "metadata"}`` dicts. Returns the
        number of vectors processed (also returned when disabled, since the records were
        prepared).
        """
        if not vectors:
            return 0
        if not self.enabled:
            logger.info(
                "[pinecone-disabled] would upsert %d vectors to namespace '%s' (index=%s)",
                len(vectors),
                namespace,
                settings.PINECONE_INDEX,
            )
            return len(vectors)
        try:
            # Pinecone accepts batches; keep them modest.
            BATCH = 100
            total = 0
            for i in range(0, len(vectors), BATCH):
                batch = vectors[i : i + BATCH]
                self.index.upsert(vectors=batch, namespace=namespace)
                total += len(batch)
            logger.info("Upserted %d vectors to Pinecone namespace '%s'", total, namespace)
            return total
        except Exception as exc:  # noqa: BLE001
            logger.exception("Pinecone upsert failed for namespace '%s'", namespace)
            raise PineconeUpsertError(
                f"Pinecone upsert failed for namespace {namespace!r}: {exc}"
            ) from exc

    def delete_ids(self, *, namespace: str, ids: list[str]) -> bool:
        """Delete specific stale vectors before a single-document re-ingest."""
        ids = [str(i) for i in ids if i]
        if not ids:
            return True
        if not self.enabled:
            logger.info("[pinecone-disabled] would delete %d ids from '%s'", len(ids), namespace)
            return True
        try:
            for i in range(0, len(ids), 1000):
                self.index.delete(ids=ids[i : i + 1000], namespace=namespace)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.exception("Pinecone id delete failed for namespace '%s'", namespace)
            raise PineconeUpsertError(
                f"Pinecone stale-vector delete failed for namespace {namespace!r}: {exc}"
            ) from exc

    def delete_namespace(self, namespace: str) -> bool:
        """
        Delete all vectors in a namespace (used by reingest).

        A namespace that doesn't exist yet (e.g. on a freshly-created index, or one being
        ingested for the first time) is NOT an error — Pinecone returns 404 "Namespace not
        found", which we treat as a successful no-op and log quietly rather than dumping a
        traceback.
        """
        if not self.enabled:
            logger.info("[pinecone-disabled] would delete namespace '%s'", namespace)
            return True
        try:
            self.index.delete(delete_all=True, namespace=namespace)
            return True
        except Exception as exc:  # noqa: BLE001
            # "Namespace not found" just means there's nothing to clear — that's fine.
            if "not found" in str(exc).lower() or "404" in str(exc):
                logger.debug("Namespace '%s' did not exist yet — nothing to clear.", namespace)
                return True
            logger.warning("Pinecone namespace delete failed for '%s': %s", namespace, exc)
            return False
