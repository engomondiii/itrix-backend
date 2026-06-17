"""
Pinecone query client.

Read-side companion to ``knowledge_core.pinecone_upserter``. Queries the index for the
nearest chunks to an embedded query vector, optionally filtered by namespace and
metadata. Imported lazily; when the engine is disabled it returns no matches so the RAG
pipeline falls back to the deterministic path.
"""

from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger("itrix")


class PineconeQueryClient:
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

        Never raises: any failure (disabled, network, bad index) yields ``[]`` so the
        caller can degrade gracefully.
        """
        if not self.enabled:
            return []
        try:
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
            logger.exception("Pinecone query failed")
            return []
