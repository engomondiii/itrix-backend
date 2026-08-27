"""
Knowledge retriever.

The visitor-facing AI is document-grounded.  Retrieval therefore has three invariants:

1. Public/company/product questions search the complete visitor knowledge corpus rather
   than one route-derived namespace.
2. Disclosure is pushed into the Pinecone query so restricted matches cannot consume the
   top-k budget and leave the model with an empty context.
3. When multiple corpus versions disagree, explicitly current/canonical documents receive
   a small rerank boost.  The model is still grounded only in source chunks; this merely
   resolves version conflicts in favour of the current source.

The attachment store is deliberately NOT part of this retriever.  Visitor uploads are
thread-scoped context assembled separately by ``with_attachment_context``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from django.conf import settings
from django.db.models import Q

from apps.ai_engine.services.disclosure_filter import allowed_levels, filter_chunks
from apps.ai_engine.services.pinecone_client import PineconeQueryClient
from apps.knowledge_core.models import KnowledgeChunk
from apps.knowledge_core.services.embedder import Embedder
from apps.knowledge_core.services.namespace_router import normalize_namespace

logger = logging.getLogger("itrix")

# General/internal platform specifications intentionally do not participate in public
# product/company answers.  Everything a visitor should learn about itriX lives in one of
# these namespaces; searching them together prevents a route label from hiding relevant
# product knowledge.
VISITOR_KNOWLEDGE_NAMESPACES: tuple[str, ...] = (
    "company",
    "technology",
    "alpha-compute",
    "alpha-core",
    "proofs",
    "licensing",
)


def _canonical_priority_for_row(row: KnowledgeChunk) -> int:
    """Use explicit source authority/currentness first; filenames are legacy fallback only."""
    doc = getattr(row, "document", None)
    if doc is not None:
        authority = str(getattr(doc, "source_authority", "") or "")
        base = {"authoritative": 100, "governing": 85, "working": 50, "legacy": 5}.get(authority, 0)
        if base:
            if not bool(getattr(doc, "is_current", True)):
                base = min(base, 5)
            return base
    blob = f"{getattr(doc, 'title', '')} {getattr(doc, 'file_path', '')}".lower()
    if "canonical" in blob or "v2.4" in blob or "v2_4" in blob:
        return 90
    return 10


def _row_to_dict(row: KnowledgeChunk, *, score=None, retrieval_backend: str = "db") -> dict:
    chunk_id = row.vector_id or str(row.id)
    return {
        "id": chunk_id,
        "chunk_id": chunk_id,
        "text": row.text,
        "heading": row.heading,
        "namespace": row.namespace,
        "disclosure_level": row.disclosure_level,
        "document_id": str(row.document_id),
        "document_title": getattr(getattr(row, "document", None), "title", ""),
        "document_path": getattr(getattr(row, "document", None), "file_path", ""),
        "canonical_priority": _canonical_priority_for_row(row),
        "source_authority": getattr(getattr(row, "document", None), "source_authority", "working"),
        "source_current": bool(getattr(getattr(row, "document", None), "is_current", True)),
        "canonical_rule": getattr(getattr(row, "document", None), "canonical_rule", ""),
        "approved_audience": list(getattr(getattr(row, "document", None), "approved_audience", None) or []),
        "allowed_journey_stages": list(getattr(getattr(row, "document", None), "allowed_journey_stages", None) or []),
        "permitted_paraphrase": getattr(getattr(row, "document", None), "permitted_paraphrase", "approved"),
        "technology_family": getattr(getattr(row, "document", None), "technology_family", "general"),
        "claim_ceiling": int(getattr(getattr(row, "document", None), "claim_ceiling", 0) or 0),
        "score": score,
        "retrieval_backend": retrieval_backend,
    }


def _normalise_namespaces(
    namespace: str | None, namespaces: Iterable[str] | None
) -> tuple[str, ...]:
    if namespaces is not None:
        out = tuple(dict.fromkeys(normalize_namespace(ns) for ns in namespaces if ns))
        return out or VISITOR_KNOWLEDGE_NAMESPACES
    if namespace:
        return (normalize_namespace(namespace),)
    return VISITOR_KNOWLEDGE_NAMESPACES


def _keyword_fallback(
    query: str, *, namespaces: tuple[str, ...], top_k: int, context: str = "public"
) -> list[dict]:
    """Offline retrieval with the same query-time disclosure budget as Pinecone."""
    permitted = allowed_levels(context) - {"prohibited"}
    qs = (
        KnowledgeChunk.objects.select_related("document")
        .filter(namespace__in=namespaces, disclosure_level__in=permitted, document__is_current=True)
        .exclude(document__permitted_paraphrase="none")
    )

    terms = [
        t
        for t in {w.strip(".,;:!?()[]{}\"'").lower() for w in (query or "").split()}
        if len(t) > 3
    ]
    if terms:
        condition = Q()
        for term in terms:
            condition |= Q(text__icontains=term) | Q(heading__icontains=term) | Q(document__title__icontains=term)
        ranked = list(qs.filter(condition)[: max(top_k * 8, 40)])
    else:
        ranked = []

    if not ranked:
        ranked = list(qs.order_by("-created_at")[: max(top_k * 4, 20)])

    def overlap(row: KnowledgeChunk) -> int:
        blob = f"{row.document.title}\n{row.heading}\n{row.text}".lower()
        return sum(blob.count(t) for t in terms)

    ranked.sort(
        key=lambda row: (_canonical_priority_for_row(row), overlap(row)), reverse=True
    )
    return [
        _row_to_dict(row, retrieval_backend="keyword_fallback")
        for row in ranked[:top_k]
    ]


def _pinecone_filter(context: str) -> dict:
    # Query-time filtering is critical.  Filtering only after top-k allows six restricted
    # matches to consume all six slots, yielding zero grounding to a public caller.
    permitted = sorted(allowed_levels(context))
    return {"disclosure_level": {"$in": permitted}}


def _rerank(chunks: list[dict], top_k: int) -> list[dict]:
    """Deduplicate and rerank semantic matches with a bounded canonical-source boost."""
    dedup: dict[str, dict] = {}
    for chunk in chunks:
        key = str(chunk.get("chunk_id") or chunk.get("id") or "")
        if not key:
            continue
        prior = dedup.get(key)
        if prior is None or float(chunk.get("score") or 0.0) > float(prior.get("score") or 0.0):
            dedup[key] = chunk

    def key(chunk: dict):
        semantic = float(chunk.get("score") or 0.0)
        priority = int(chunk.get("canonical_priority") or 0)
        # At most +0.10: enough to resolve close version conflicts without making a
        # product white paper beat a clearly more relevant technology chunk.
        return semantic + min(priority, 100) / 1000.0

    return sorted(dedup.values(), key=key, reverse=True)[:top_k]


class KnowledgeRetriever:
    def __init__(self):
        self.engine_on = settings.ENABLE_AI_ENGINE

    def retrieve(
        self,
        query: str,
        *,
        namespace: str | None = None,
        namespaces: Iterable[str] | None = None,
        top_k: int = 8,
        context: str = "public",
        customer_scope: str = "",
    ) -> list[dict]:
        """Return source-grounded chunks most relevant to ``query``."""
        selected_namespaces = _normalise_namespaces(namespace, namespaces)
        chunks: list[dict] = []

        if self.engine_on:
            try:
                vector = Embedder().embed_one(query)
                query_client = PineconeQueryClient()
                raw: list[dict] = []

                # Pinecone namespaces are isolated; query each relevant namespace, then
                # merge/rerank.  top_k per namespace intentionally over-fetches a little
                # so a broad "what is itriX?" question can surface company + both products.
                per_namespace_k = max(4, top_k)
                for ns in selected_namespaces:
                    matches = query_client.query(
                        vector=vector,
                        top_k=per_namespace_k,
                        namespace=ns,
                        metadata_filter=_pinecone_filter(context),
                    )
                    for match in matches:
                        match["_queried_namespace"] = ns
                    raw.extend(matches)

                ids = [m.get("id") for m in raw if m.get("id")]
                by_id = {
                    c.vector_id: c
                    for c in KnowledgeChunk.objects.select_related("document").filter(
                        vector_id__in=ids
                    )
                }

                for match in raw:
                    row = by_id.get(match.get("id"))
                    metadata = match.get("metadata") or {}
                    if row:
                        item = _row_to_dict(
                            row,
                            score=match.get("score"),
                            retrieval_backend="pinecone",
                        )
                        item["canonical_priority"] = int(
                            metadata.get("canonical_priority")
                            or item.get("canonical_priority")
                            or 0
                        )
                        chunks.append(item)
                    elif metadata:
                        # DB/Pinecone drift should be visible rather than silently losing
                        # a usable match.  Validation will flag the count mismatch.
                        chunks.append(
                            {
                                "id": match.get("id"),
                                "chunk_id": match.get("id"),
                                "text": metadata.get("preview", ""),
                                "heading": metadata.get("heading", ""),
                                "namespace": metadata.get("namespace") or match.get("_queried_namespace", ""),
                                "disclosure_level": metadata.get("disclosure_level", "public"),
                                "document_id": metadata.get("document_id"),
                                "document_title": metadata.get("document_title", ""),
                                "canonical_priority": int(metadata.get("canonical_priority") or 0),
                                "score": match.get("score"),
                                "retrieval_backend": "pinecone",
                            }
                        )

                chunks = _rerank(chunks, top_k)
            except Exception:  # noqa: BLE001
                logger.exception("Vector retrieval failed; using keyword fallback")
                chunks = []

        if not chunks:
            chunks = _keyword_fallback(
                query, namespaces=selected_namespaces, top_k=top_k, context=context
            )

        # Belt-and-braces post-filter.  Query-time metadata filtering protects the top-k
        # budget; this protects against stale/incorrect remote metadata.
        return filter_chunks(chunks, context=context, customer_scope=customer_scope)


def retrieve_knowledge(query: str, **kwargs) -> list[dict]:
    return KnowledgeRetriever().retrieve(query, **kwargs)
