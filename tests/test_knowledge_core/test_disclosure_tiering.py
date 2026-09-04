"""Knowledge-source folder disclosure policy.

Folder placement is an authorization decision.  A source stored under controlled,
authorized, agreement-gated, private-workspace or role-restricted material must retain
that tier during registration; the ingestion command may never silently publish it merely
because the document looks product/research-related.
"""

from __future__ import annotations

import pathlib

from apps.knowledge_core.management.commands.register_knowledge_docs import (
    FOLDER_DISCLOSURE,
    SUPERSEDED_FILENAMES,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
KNOWLEDGE_DOCS = REPO_ROOT / "knowledge_docs"


def _files_in(folder: str):
    path = KNOWLEDGE_DOCS / folder
    if not path.exists():
        return []
    return [p for p in sorted(path.iterdir()) if p.is_file() and p.name != ".gitkeep"]


def test_source_folders_keep_their_explicit_disclosure_tier():
    assert FOLDER_DISCLOSURE["public"] == "public"
    assert FOLDER_DISCLOSURE["controlled_public"] == "controlled_public"
    assert FOLDER_DISCLOSURE["authorized"] == "authorized"
    assert FOLDER_DISCLOSURE["nda_only"] == "nda_only"


def test_operational_and_customer_material_are_not_public_by_default():
    assert FOLDER_DISCLOSURE["internal_only"] == "internal_only"
    assert FOLDER_DISCLOSURE["customer_contract"] == "customer_contract"


def test_current_alpha_whitepaper_is_in_the_public_source_set():
    assert (KNOWLEDGE_DOCS / "public" / "WP_ALPHA_Compute_Core_v2.4.docx").exists()
    assert (KNOWLEDGE_DOCS / "public" / "itrix_product_canonical_v2_4.md").exists()


def test_superseded_product_doctrine_is_explicitly_excluded_from_registration():
    stale = {
        "5_1_ALPHA_Compute_Overview_v2.0.docx",
        "5_2_ALPHA Core Product Overview_V2.0.docx",
        "alpha_compute_problemology_public.md",
        "alpha_core_problemology_public.md",
        "Brand Story of itriX.docx",
        "WP_Alpha Compute Core.docx",
        "README_Astop.txt",
    }
    assert stale <= SUPERSEDED_FILENAMES



def test_september_astop_sources_exist_in_the_governed_source_set():
    assert (KNOWLEDGE_DOCS / "internal_only" / "ASTOP_Productization_GTM_Plan_v2.3.docx").exists()
    assert (KNOWLEDGE_DOCS / "internal_only" / "itriX_AI_Sales_Platform_MVP_Guide_for_Fidel_v3.5.docx").exists()
    assert (KNOWLEDGE_DOCS / "internal_only" / "itriX_White_Paper_v3.5.docx").exists()
    assert (KNOWLEDGE_DOCS / "controlled_public" / "prism-paper-current_v2.pdf").exists()
    assert (KNOWLEDGE_DOCS / "public" / "astop_prism_public_safe_v2_3.md").exists()


def test_noncurrent_astop_pricing_chunk_cannot_be_retrieved(db):
    from apps.ai_engine.services.knowledge_retriever import _keyword_fallback
    from apps.knowledge_core.models import KnowledgeChunk, KnowledgeDocument

    stale = KnowledgeDocument.objects.create(
        title="Legacy ASTOP Team pricing",
        file_path="knowledge_docs/internal_only/legacy_astop_pricing.md",
        namespace="astop",
        disclosure_level="public",
        source_authority="legacy",
        is_current=False,
        permitted_paraphrase="approved",
    )
    KnowledgeChunk.objects.create(
        document=stale, namespace="astop", disclosure_level="public", chunk_index=0,
        text="ASTOP Team costs $99/month and can be purchased by public checkout.",
    )

    rows = _keyword_fallback(
        "What does ASTOP cost?", namespaces=("astop",), top_k=8,
        candidate_levels={"public"}, audience="visitor", journey_stage="PUBLIC-SAFE", claim_ceiling=2,
    )
    assert rows == []
