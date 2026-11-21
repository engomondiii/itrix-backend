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
import os
from functools import lru_cache

from django.conf import settings

logger = logging.getLogger("itrix")


def _timeout_seconds() -> float:
    try:
        return float(getattr(settings, "AI_CALL_TIMEOUT_SECONDS", 20))
    except (TypeError, ValueError):
        return 20.0


@lru_cache(maxsize=4)
def _shared_index(process_id, api_key, index_name):
    """Share the HTTP pool across generation threads, never across worker forks.

    Query requests already use this same index concurrently across namespaces.
    Only the connection pool is reused: results and authorization remain per turn.
    The process/config key isolates forks and credential/index rotations.
    """
    from pinecone import Pinecone
    pc = Pinecone(api_key=api_key)
    try:
        return pc.Index(index_name)
    finally:
        pc.close()


class PineconeQueryClient:
    def __init__(self):
        self.enabled = settings.ENABLE_AI_ENGINE and bool(settings.PINECONE_API_KEY)
        self._index = None

    @property
    def index(self):
        if self._index is None:
            self._index = _shared_index(
                os.getpid(), settings.PINECONE_API_KEY, settings.PINECONE_INDEX,
            )
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
            # The retriever loads current text and access rules from PostgreSQL.
            # Returning duplicate remote metadata only adds transfer/decoding time.
            try:
                result = self.index.query(
                    vector=vector,
                    top_k=top_k,
                    namespace=namespace or None,
                    include_metadata=False,
                    filter=metadata_filter or None,
                    timeout=int(_timeout_seconds()),
                )
            except TypeError:
                result = self.index.query(
                    vector=vector,
                    top_k=top_k,
                    namespace=namespace or None,
                    include_metadata=False,
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
