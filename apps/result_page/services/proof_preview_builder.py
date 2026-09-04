"""Source-driven evidence preview for My Review.

Evidence appears only when the visitor's safe workload context makes the technology family
material *and* a current applicable Knowledge source exists.  No route gets a universal
FQNM/arXiv proof by default.
"""
from __future__ import annotations

import re

_FAMILY_PATTERNS = {
    "fqnm": re.compile(r"\b(conservation|conservative|hyperbolic|transport|flux|finite volume|pde|fluid|cfd)\b", re.I),
    "cre": re.compile(r"\b(complex[- ]valued|complex operator|hermitian|hpd|conjugate|complex matrix)\b", re.I),
    "axiom": re.compile(r"\b(algebraic state|observation|projection|reconstruction|tensor|algebraic representation)\b", re.I),
}


def applicable_families(workload_text: str) -> set[str]:
    text = workload_text or ""
    return {family for family, pattern in _FAMILY_PATTERNS.items() if pattern.search(text)}


def _status_for(doc) -> str:
    blob = f"{doc.title} {doc.file_path}".lower()
    if "arxiv" in blob:
        return "arXiv preprint"
    if "thesis" in blob:
        return "master's thesis"
    if "overview" in blob or "white paper" in blob or "wp_" in blob:
        return "technical source"
    return "current source"


def _reference_for(doc) -> str:
    blob = f"{doc.title} {doc.file_path}"
    if "2604.06947" in blob:
        return "arXiv:2604.06947 [math.NA]"
    if "FQNM_arXiv" in blob or "fqnm arxiv" in blob.lower():
        return "arXiv:2604.06947 [math.NA]"
    # Do not fabricate an external citation from a local/internal filename.
    return doc.title


def build_proof_preview(
    *, product_route: str, tier: int, context: str = "public", workload_text: str = ""
) -> list[dict]:
    del product_route, tier  # product routing is not mathematical applicability
    families = applicable_families(workload_text)
    if not families:
        return []

    try:
        from apps.ai_engine.services.disclosure_filter import allowed_levels
        from apps.knowledge_core.models import KnowledgeDocument

        permitted = allowed_levels(context)
        docs = (
            KnowledgeDocument.objects.filter(
                is_current=True,
                technology_family__in=sorted(families),
                disclosure_level__in=permitted,
            )
            .exclude(permitted_paraphrase="none")
            .order_by("technology_family", "-source_authority", "title")
        )
    except Exception:
        return []

    out: list[dict] = []
    seen: set[str] = set()
    for doc in docs:
        family = str(doc.technology_family or "")
        if family in seen:
            continue
        # Evidence preview requires an evidentiary source, not merely a product page.
        blob = f"{doc.title} {doc.file_path}".lower()
        if not any(token in blob for token in ("arxiv", "thesis", "paper", "comparison")):
            continue
        seen.add(family)
        out.append({
            "title": doc.title,
            "status": _status_for(doc),
            "disclosure": doc.disclosure_level,
            "reference": _reference_for(doc),
            "technologyFamily": family,
        })
    return out[:3]
