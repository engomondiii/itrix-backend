"""Pinecone persistence helpers for the configured itriX Knowledge index."""

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

    def namespace_counts(self) -> dict[str, int]:
        """Return namespace -> vector count for the configured index only.

        This is deliberately index-scoped. Reconciliation never lists accounts or other
        indexes; ``PINECONE_INDEX`` is the outer safety boundary selected by the operator.
        """
        if not self.enabled:
            return {}
        try:
            stats = self.index.describe_index_stats()
            namespaces = getattr(stats, "namespaces", None)
            if namespaces is None and isinstance(stats, dict):
                namespaces = stats.get("namespaces", {})
            out: dict[str, int] = {}
            for name, info in dict(namespaces or {}).items():
                count = getattr(info, "vector_count", None)
                if count is None and isinstance(info, dict):
                    count = info.get("vector_count", 0)
                out[str(name)] = int(count or 0)
            return out
        except Exception as exc:  # noqa: BLE001
            logger.exception("Pinecone namespace inventory failed")
            raise PineconeUpsertError("Could not inventory configured Pinecone namespaces") from exc

    def upsert(self, *, namespace: str, vectors: list[dict]) -> int:
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
            batch_size = 100
            total = 0
            for i in range(0, len(vectors), batch_size):
                batch = vectors[i : i + batch_size]
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
            if "not found" in str(exc).lower() or "404" in str(exc):
                logger.debug(
                    "Namespace '%s' did not exist while deleting stale ids — nothing to delete.",
                    namespace,
                )
                return True
            logger.exception("Pinecone id delete failed for namespace '%s'", namespace)
            raise PineconeUpsertError(
                f"Pinecone stale-vector delete failed for namespace {namespace!r}: {exc}"
            ) from exc

    def delete_namespace(self, namespace: str) -> bool:
        """Delete every vector in one namespace of the configured index."""
        if not self.enabled:
            logger.info("[pinecone-disabled] would delete namespace '%s'", namespace)
            return True
        try:
            self.index.delete(delete_all=True, namespace=namespace)
            return True
        except Exception as exc:  # noqa: BLE001
            if "not found" in str(exc).lower() or "404" in str(exc):
                logger.debug("Namespace '%s' did not exist yet — nothing to clear.", namespace)
                return True
            logger.exception("Pinecone namespace delete failed for '%s'", namespace)
            raise PineconeUpsertError(
                f"Could not clear Pinecone namespace {namespace!r}"
            ) from exc
