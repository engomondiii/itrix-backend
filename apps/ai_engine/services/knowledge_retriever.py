"""Governed Knowledge Core retrieval.

Retrieval is not authorization.  Applicable source metadata is enforced before chunks can
enter model context: currentness, disclosure/content authorization, audience, journey
stage, source precedence and claim ceiling.  Hard facts additionally resolve through the
structured HardFact registry; prose similarity cannot upgrade a filing to a grant or turn
internal commercial doctrine into a customer-facing rule.
"""
from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterable

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from apps.ai_engine.services.disclosure_filter import (
    filter_chunks,
    query_candidate_levels,
)
from apps.ai_engine.services.pinecone_client import PineconeQueryClient
from apps.knowledge_core.models import (
    ContentAuthorization,
    HardFact,
    KnowledgeChunk,
    KnowledgeConflict,
)
from apps.knowledge_core.services.embedder import Embedder
from apps.knowledge_core.services.namespace_router import normalize_namespace

logger = logging.getLogger("itrix")

VISITOR_KNOWLEDGE_NAMESPACES: tuple[str, ...] = (
    "company", "astop", "technology", "alpha-compute", "alpha-core", "proofs", "licensing",
)
_AUTHORITY_RANK = {"authoritative": 4, "governing": 3, "working": 2, "legacy": 1}
_HARD_FACT_QUERY = re.compile(
    r"\b(patent|patents|filing|application number|grant(?:ed)?|prosecution|ownership|"
    r"incorporat|company registered|commercial policy|revenue shar|value shar|royalt|"
    r"benchmark|customer|transaction)\b",
    re.I,
)
_PATENT_QUERY = re.compile(r"\b(patent|filing|application|grant|prosecution)\b", re.I)


def _canonical_priority_for_row(row: KnowledgeChunk) -> int:
    doc = getattr(row, "document", None)
    authority = str(getattr(doc, "source_authority", "") or "")
    base = {"authoritative": 100, "governing": 85, "working": 50, "legacy": 5}.get(authority, 0)
    if not bool(getattr(doc, "is_current", True)):
        return 0
    return base


def _row_to_dict(row: KnowledgeChunk, *, score=None, retrieval_backend: str = "db") -> dict:
    doc = row.document
    chunk_id = row.vector_id or str(row.id)
    return {
        "id": chunk_id,
        "chunk_id": chunk_id,
        "text": row.text,
        "heading": row.heading,
        "namespace": row.namespace,
        "disclosure_level": row.disclosure_level,
        "document_id": str(row.document_id),
        "document_title": getattr(doc, "title", ""),
        "document_path": getattr(doc, "file_path", ""),
        "canonical_priority": _canonical_priority_for_row(row),
        "source_authority": getattr(doc, "source_authority", "working"),
        "source_current": bool(getattr(doc, "is_current", True)),
        "verified_at": getattr(getattr(doc, "verified_at", None), "isoformat", lambda: "")(),
        "canonical_rule": getattr(doc, "canonical_rule", ""),
        "approved_audience": list(getattr(doc, "approved_audience", None) or []),
        "allowed_journey_stages": list(getattr(doc, "allowed_journey_stages", None) or []),
        "permitted_paraphrase": getattr(doc, "permitted_paraphrase", "approved"),
        "technology_family": getattr(doc, "technology_family", "general"),
        "claim_ceiling": int(getattr(doc, "claim_ceiling", 0) or 0),
        "entity_type": getattr(doc, "entity_type", "mixed"),
        "evidence_status": getattr(doc, "evidence_status", "mixed"),
        "score": score,
        "retrieval_backend": retrieval_backend,
    }


def _normalise_namespaces(namespace: str | None, namespaces: Iterable[str] | None) -> tuple[str, ...]:
    if namespaces is not None:
        out = tuple(dict.fromkeys(normalize_namespace(ns) for ns in namespaces if ns))
        return out or VISITOR_KNOWLEDGE_NAMESPACES
    if namespace:
        return (normalize_namespace(namespace),)
    return VISITOR_KNOWLEDGE_NAMESPACES


def _audience_allowed(values: list[str], audience: str) -> bool:
    values = [str(v).strip().lower() for v in (values or []) if str(v).strip()]
    if not values:
        return True
    return "all" in values or "general" in values or (audience or "general").lower() in values


def _stage_allowed(values: list[str], journey_stage: str) -> bool:
    values = [str(v).strip().lower() for v in (values or []) if str(v).strip()]
    if not values:
        return True
    stage = (journey_stage or "").strip().lower()
    return bool(stage and (stage in values or "all" in values))


def _metadata_applicable(chunk: dict, *, audience: str, journey_stage: str, claim_ceiling: int) -> bool:
    if not bool(chunk.get("source_current", True)):
        return False
    if (chunk.get("permitted_paraphrase") or "approved") == "none":
        return False
    if not _audience_allowed(list(chunk.get("approved_audience") or []), audience):
        return False
    if not _stage_allowed(list(chunk.get("allowed_journey_stages") or []), journey_stage):
        return False
    source_ceiling = int(chunk.get("claim_ceiling") or 0)
    if claim_ceiling and source_ceiling and source_ceiling > claim_ceiling:
        return False
    return True


def _authorization_document_ids(subjects: dict[str, str] | None) -> set[str]:
    pairs = [(str(k), str(v)) for k, v in (subjects or {}).items() if v]
    if not pairs:
        return set()
    q = Q()
    for kind, subject_id in pairs:
        q |= Q(subject_kind=kind, subject_id=subject_id)
    now = timezone.now()
    qs = ContentAuthorization.objects.filter(q, active=True).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    )
    return {str(x) for x in qs.values_list("document_id", flat=True)}


def _pinecone_filter(levels: set[str]) -> dict:
    return {"disclosure_level": {"$in": sorted(levels)}}


def _keyword_fallback(
    query: str, *, namespaces: tuple[str, ...], top_k: int, candidate_levels: set[str],
    audience: str, journey_stage: str, claim_ceiling: int,
) -> list[dict]:
    qs = (
        KnowledgeChunk.objects.select_related("document")
        .filter(namespace__in=namespaces, disclosure_level__in=candidate_levels, document__is_current=True)
        .exclude(document__permitted_paraphrase="none")
    )
    terms = [
        t for t in {w.strip(".,;:!?()[]{}\"'").lower() for w in (query or "").split()}
        if len(t) > 3
    ]
    if terms:
        condition = Q()
        for term in terms:
            condition |= Q(text__icontains=term) | Q(heading__icontains=term) | Q(document__title__icontains=term)
        ranked = list(qs.filter(condition)[: max(top_k * 12, 80)])
    else:
        ranked = list(qs.order_by("-created_at")[: max(top_k * 8, 40)])

    def overlap(row: KnowledgeChunk) -> int:
        blob = f"{row.document.title}\n{row.heading}\n{row.text}".lower()
        return sum(blob.count(t) for t in terms)

    ranked.sort(key=lambda row: (_canonical_priority_for_row(row), overlap(row)), reverse=True)
    out = [_row_to_dict(row, retrieval_backend="keyword_fallback") for row in ranked]
    out = [c for c in out if _metadata_applicable(c, audience=audience, journey_stage=journey_stage, claim_ceiling=claim_ceiling)]
    return out[: max(top_k * 3, top_k)]


def _dedupe(chunks: list[dict]) -> list[dict]:
    dedup: dict[str, dict] = {}
    for chunk in chunks:
        key = str(chunk.get("chunk_id") or chunk.get("id") or "")
        if not key:
            continue
        prior = dedup.get(key)
        if prior is None or float(chunk.get("score") or 0.0) > float(prior.get("score") or 0.0):
            dedup[key] = chunk
    return list(dedup.values())


def _record_same_authority_conflict(query: str, chunks: list[dict]) -> None:
    # We can only assert a conflict from explicit canonical rules; semantic disagreement
    # is never guessed from arbitrary prose.
    rules: dict[str, set[str]] = {}
    docs: dict[str, set[str]] = {}
    for c in chunks:
        rule = str(c.get("canonical_rule") or "").strip()
        if not rule:
            continue
        authority = str(c.get("source_authority") or "working")
        rules.setdefault(authority, set()).add(rule)
        docs.setdefault(authority, set()).add(str(c.get("document_id") or ""))
    for authority, values in rules.items():
        if len(values) <= 1:
            continue
        fp = hashlib.sha256((query or "").strip().lower().encode()).hexdigest()
        try:
            KnowledgeConflict.objects.get_or_create(
                query_fingerprint=fp,
                authority=authority,
                resolved=False,
                defaults={
                    "topic": (query or "")[:160],
                    "document_ids": sorted(x for x in docs.get(authority, set()) if x),
                    "detail": "Conflicting explicit canonical_rule values at equal source authority.",
                },
            )
        except Exception:  # audit persistence must not make retrieval unavailable
            logger.exception("Could not persist Knowledge Core same-authority conflict")


def _apply_source_precedence(query: str, chunks: list[dict], *, top_k: int) -> list[dict]:
    chunks = _dedupe(chunks)
    if not chunks:
        return []
    _record_same_authority_conflict(query, chunks)
    hard = bool(_HARD_FACT_QUERY.search(query or ""))
    if hard:
        highest = max(_AUTHORITY_RANK.get(str(c.get("source_authority") or "working"), 0) for c in chunks)
        chunks = [c for c in chunks if _AUTHORITY_RANK.get(str(c.get("source_authority") or "working"), 0) == highest]
    # Authority is a primary ordering key, not a fractional semantic bonus. For ordinary
    # multi-topic questions it orders applicable evidence without discarding other topics.
    chunks.sort(
        key=lambda c: (
            _AUTHORITY_RANK.get(str(c.get("source_authority") or "working"), 0),
            int(c.get("canonical_priority") or 0),
            float(c.get("score") or 0.0),
        ),
        reverse=True,
    )
    return chunks[:top_k]


def _structured_hard_facts(
    query: str, *, context: str, audience: str, claim_ceiling: int,
) -> list[dict]:
    if not _HARD_FACT_QUERY.search(query or ""):
        return []
    qs = HardFact.objects.filter(is_current=True)
    if _PATENT_QUERY.search(query or ""):
        qs = qs.filter(category=HardFact.Category.PATENT)
    if context != "internal":
        qs = qs.filter(disclosure_level__in=["public", "controlled_public"])
    facts = []
    for fact in qs.order_by("-last_verified_at", "key")[:20]:
        if not _audience_allowed(list(fact.approved_audience or []), audience):
            continue
        if claim_ceiling and fact.claim_ceiling and fact.claim_ceiling > claim_ceiling:
            continue
        text = (fact.public_statement or "").strip()
        if not text:
            # Internal structured records may be useful to team agents but do not expose
            # internal references as if they were official patent/application numbers.
            if context == "internal":
                status = fact.prosecution_status or fact.publication_status or "status not recorded"
                text = f"{fact.key}: {status}."
                if fact.official_application_number:
                    text += f" Official application number: {fact.official_application_number}."
                if fact.verified_grant_number:
                    text += f" Verified grant number: {fact.verified_grant_number}."
            else:
                continue
        facts.append({
            "id": f"hard-fact:{fact.id}",
            "chunk_id": f"hard-fact:{fact.id}",
            "text": text,
            "heading": "Authoritative fact registry",
            "namespace": "company",
            "disclosure_level": fact.disclosure_level,
            "document_id": str(fact.source_document_id or ""),
            "document_title": "Authoritative fact registry",
            "canonical_priority": 110,
            "source_authority": fact.source_authority,
            "source_current": fact.is_current,
            "canonical_rule": "Structured hard fact",
            "approved_audience": list(fact.approved_audience or []),
            "allowed_journey_stages": [],
            "permitted_paraphrase": "approved",
            "technology_family": "general",
            "claim_ceiling": fact.claim_ceiling,
            "score": 1.0,
            "retrieval_backend": "hard_fact_registry",
        })
    return facts


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
        authorization_subjects: dict[str, str] | None = None,
        nda_signed: bool = False,
        contract_executed: bool = False,
        audience: str = "general",
        journey_stage: str = "",
        claim_ceiling: int = 0,
    ) -> list[dict]:
        selected_namespaces = _normalise_namespaces(namespace, namespaces)
        auth_doc_ids = _authorization_document_ids(authorization_subjects)
        candidate_levels = query_candidate_levels(
            context,
            has_explicit_authorization=bool(auth_doc_ids),
            nda_signed=nda_signed,
            contract_executed=contract_executed,
        )
        chunks: list[dict] = []

        if self.engine_on:
            try:
                vector = Embedder().embed_one(query)
                query_client = PineconeQueryClient()
                raw: list[dict] = []
                per_namespace_k = max(12, top_k * 4)
                for ns in selected_namespaces:
                    matches = query_client.query(
                        vector=vector,
                        top_k=per_namespace_k,
                        namespace=ns,
                        metadata_filter=_pinecone_filter(candidate_levels),
                    )
                    raw.extend(matches)

                ids = [m.get("id") for m in raw if m.get("id")]
                by_id = {
                    c.vector_id: c
                    for c in KnowledgeChunk.objects.select_related("document").filter(
                        vector_id__in=ids,
                        document__is_current=True,
                    )
                }
                for match in raw:
                    row = by_id.get(match.get("id"))
                    # DB metadata is authoritative. Pinecone-only drift fails closed rather
                    # than trusting an old remote disclosure/source label.
                    if not row:
                        continue
                    item = _row_to_dict(row, score=match.get("score"), retrieval_backend="pinecone")
                    if _metadata_applicable(item, audience=audience, journey_stage=journey_stage, claim_ceiling=claim_ceiling):
                        chunks.append(item)
            except Exception:  # noqa: BLE001
                logger.exception("Vector retrieval failed; using keyword fallback")
                chunks = []

        if not chunks:
            chunks = _keyword_fallback(
                query,
                namespaces=selected_namespaces,
                top_k=max(top_k * 3, top_k),
                candidate_levels=candidate_levels,
                audience=audience,
                journey_stage=journey_stage,
                claim_ceiling=claim_ceiling,
            )

        chunks = filter_chunks(
            chunks,
            context=context,
            customer_scope=customer_scope,
            authorized_document_ids=auth_doc_ids,
            nda_signed=nda_signed,
            contract_executed=contract_executed,
        )
        chunks = _apply_source_precedence(query, chunks, top_k=top_k)

        facts = _structured_hard_facts(
            query, context=context, audience=audience, claim_ceiling=claim_ceiling
        )
        if facts:
            # A structured hard fact is authoritative over prose. Keep relevant prose as
            # supporting evidence only after the registry statement.
            return (facts + chunks)[:top_k]
        return chunks[:top_k]


def retrieve_knowledge(query: str, **kwargs) -> list[dict]:
    return KnowledgeRetriever().retrieve(query, **kwargs)
