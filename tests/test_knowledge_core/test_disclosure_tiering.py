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
    }
    assert stale <= SUPERSEDED_FILENAMES

