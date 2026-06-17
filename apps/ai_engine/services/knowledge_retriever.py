"""
Knowledge retriever.

Given a query (the visitor's prompt + routing context), returns the most relevant
disclosure-filtered knowledge chunks. When the AI engine is on, it embeds the query and
queries Pinecone; results are then disclosure-filtered. When offline, it degrades to a
lightweight keyword match over the locally stored ``KnowledgeChunk`` rows (already
disclosure-tagged), so retrieval still returns sensible, safe context with no API key.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db.models import Q

from apps.ai_engine.services.disclosure_filter import filter_chunks
from apps.ai_engine.services.pinecone_client import PineconeQueryClient
from apps.knowledge_core.models import KnowledgeChunk
from apps.knowledge_core.services.embedder import Embedder
from apps.knowledge_core.services.namespace_router import normalize_namespace

logger = logging.getLogger("itrix")


def _row_to_dict(row: KnowledgeChunk) -> dict:
    return {
        "id": row.vector_id or str(row.id),
        "text": row.text,
        "heading": row.heading,
        "namespace": row.namespace,
        "disclosure_level": row.disclosure_level,
        "document_id": str(row.document_id),
        "score": None,
    }


def _keyword_fallback(query: str, *, namespace: str | None, top_k: int) -> list[dict]:
    """Offline retrieval: rank locally stored chunks by simple keyword overlap."""
    qs = KnowledgeChunk.objects.all()
    if namespace:
        qs = qs.filter(namespace=normalize_namespace(namespace))

    terms = [t for t in {w.strip(".,;:!?()").lower() for w in (query or "").split()} if len(t) > 3]
    if terms:
        condition = Q()
        for term in terms:
            condition |= Q(text__icontains=term) | Q(heading__icontains=term)
        ranked = list(qs.filter(condition)[: top_k * 3])
    else:
        ranked = []

    if not ranked:
        # Fall back to most recent chunks in the namespace (still disclosure-tagged).
        ranked = list(qs.order_by("-created_at")[:top_k])

    # Score by term hits for a stable-ish ordering.
    def score(row: KnowledgeChunk) -> int:
        blob = f"{row.heading}\n{row.text}".lower()
        return sum(blob.count(t) for t in terms)

    ranked.sort(key=score, reverse=True)
    return [_row_to_dict(r) for r in ranked[:top_k]]


class KnowledgeRetriever:
    def __init__(self):
        self.engine_on = settings.ENABLE_AI_ENGINE

    def retrieve(
        self,
        query: str,
        *,
        namespace: str | None = None,
        top_k: int = 8,
        context: str = "public",
    ) -> list[dict]:
        """Return disclosure-filtered chunks most relevant to ``query``."""
        chunks: list[dict] = []

        if self.engine_on:
            try:
                vector = Embedder().embed_one(query)
                raw = PineconeQueryClient().query(
                    vector=vector,
                    top_k=top_k,
                    namespace=normalize_namespace(namespace) if namespace else None,
                )
                # Hydrate text from DB by vector_id where possible.
                by_id = {
                    c.vector_id: c
                    for c in KnowledgeChunk.objects.filter(
                        vector_id__in=[m["id"] for m in raw if m.get("id")]
                    )
                }
                for m in raw:
                    row = by_id.get(m.get("id"))
                    if row:
                        d = _row_to_dict(row)
                        d["score"] = m.get("score")
                        chunks.append(d)
                    elif m.get("metadata"):
                        md = m["metadata"]
                        chunks.append(
                            {
                                "id": m.get("id"),
                                "text": md.get("preview", ""),
                                "heading": md.get("heading", ""),
                                "namespace": md.get("namespace", ""),
                                "disclosure_level": md.get("disclosure_level", "public"),
                                "document_id": md.get("document_id"),
                                "score": m.get("score"),
                            }
                        )
            except Exception:  # noqa: BLE001
                logger.exception("Vector retrieval failed; using keyword fallback")
                chunks = []

        if not chunks:
            chunks = _keyword_fallback(query, namespace=namespace, top_k=top_k)

        return filter_chunks(chunks, context=context)


def retrieve_knowledge(query: str, **kwargs) -> list[dict]:
    return KnowledgeRetriever().retrieve(query, **kwargs)
