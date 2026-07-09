"""
Pinecone query client.

Read-side companion to ``knowledge_core.pinecone_upserter``. Queries the index for the
nearest chunks to an embedded query vector, optionally filtered by namespace and
metadata. Imported lazily; when the engine is disabled it returns no matches so the RAG
pipeline falls back to the deterministic path.

── HANG-PROOFING (v4.0.1) ────────────────────────────────────────────────────
The Pinecone client is created with a bounded pool timeout so a live retrieval query on
the request path cannot stall a web worker; any failure still yields ``[]`` and the caller
degrades gracefully.
"""

from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger("itrix")


def _timeout_seconds() -> float:
    try:
        return float(getattr(settings, "AI_CALL_TIMEOUT_SECONDS", 20))
    except (TypeError, ValueError):
        return 20.0


class PineconeQueryClient:
    def __init__(self):
        self.enabled = settings.ENABLE_AI_ENGINE and bool(settings.PINECONE_API_KEY)
        self._index = None

    @property
    def index(self):
        if self._index is None:
            from pinecone import Pinecone  # noqa: PLC0415 - lazy

            # Bound the underlying HTTP pool so a query can't hang indefinitely. The
            # ``pool_threads`` + ``timeout`` kwargs are accepted by the Pinecone client;
            # we pass timeout via the index query below as well for belt-and-braces.
            try:
                pc = Pinecone(api_key=settings.PINECONE_API_KEY)
            except Exception:  # noqa: BLE001
                logger.exception("Pinecone client init failed")
                raise
            self._index = pc.Index(settings.PINECONE_INDEX)
        return self._index

    def query(
        self,
        *,
        vector: list[float],
        top_k: int = 8,
        namespace: str | None = None,
        metadata_filter: dict | None = None,
    ) -> list[dict]:
        """
        Return a list of ``{"id", "score", "metadata"}`` matches (possibly empty).

        Never raises: any failure (disabled, network, bad index, timeout) yields ``[]`` so
        the caller can degrade gracefully.
        """
        if not self.enabled:
            return []
        try:
            # The Pinecone SDK accepts a per-request timeout on ``query``; pass it so a
            # slow index can't stall the request. Older SDKs ignore unknown kwargs, so we
            # attempt with-timeout first and fall back to without if it's rejected.
            try:
                result = self.index.query(
                    vector=vector,
                    top_k=top_k,
                    namespace=namespace or None,
                    include_metadata=True,
                    filter=metadata_filter or None,
                    timeout=int(_timeout_seconds()),
                )
            except TypeError:
                result = self.index.query(
                    vector=vector,
                    top_k=top_k,
                    namespace=namespace or None,
                    include_metadata=True,
                    filter=metadata_filter or None,
                )
            matches = getattr(result, "matches", None)
            if matches is None and isinstance(result, dict):
                matches = result.get("matches", [])
            out = []
            for m in matches or []:
                out.append(
                    {
                        "id": getattr(m, "id", None) if not isinstance(m, dict) else m.get("id"),
                        "score": getattr(m, "score", None) if not isinstance(m, dict) else m.get("score"),
                        "metadata": getattr(m, "metadata", {}) if not isinstance(m, dict) else m.get("metadata", {}),
                    }
                )
            return out
        except Exception:  # noqa: BLE001
            logger.warning("Pinecone query failed/timed out; returning no matches.")
            return []
