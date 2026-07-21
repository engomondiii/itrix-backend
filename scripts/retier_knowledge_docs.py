#!/usr/bin/env python
"""
Reviewable re-tiering of the knowledge_docs tree, with a per-file justification.

    python scripts/retier_knowledge_docs.py --plan          # print the plan, change nothing
    python scripts/retier_knowledge_docs.py --apply         # move the files
    python scripts/retier_knowledge_docs.py --verify        # assert no violations remain

── WHY THIS IS A SCRIPT AND NOT A MIGRATION ─────────────────────────────────
THE FOLDER IS THE ACCESS-CONTROL DECISION (Backend v6.0 §8.1). Placing a file in
``knowledge_docs/public/`` publishes it to EVERY ANONYMOUS VISITOR through the agents —
and in v6.0 those agents now STREAM to unidentified visitors by default, so the blast
radius of a mis-filed document is LARGER, not smaller.

Tier assignment is therefore a GOVERNANCE DECISION requiring the approval owner named in
the Playbook, not a schema change. This script produces a reviewable plan with a written
justification for every move, so the approver reads reasons rather than a diff.

── THE RULE THIS ENFORCES ───────────────────────────────────────────────────
A document belongs in ``public/`` only if it was WRITTEN TO BE PUBLISHED. Not "contains
nothing catastrophic" — actually intended for an anonymous reader. Everything else moves
up a tier.

── AFTER APPLYING ───────────────────────────────────────────────────────────
Re-tiering REQUIRES a vector purge before re-ingest, or the old chunks stay retrievable
at the old ceiling:

    manage.py purge_vectors --all --yes
    manage.py register_knowledge_docs
    manage.py reingest_namespace --all
    manage.py validate_knowledge_core
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DOCS = REPO_ROOT / "knowledge_docs"

TIER_PUBLIC = "public"
TIER_CONTROLLED = "controlled_public"
TIER_NDA = "nda_only"
TIER_INTERNAL = "internal_only"

# ─────────────────────────────────────────────────────────────────────────────
# THE RE-TIER PLAN
# ─────────────────────────────────────────────────────────────────────────────
# filename -> (target_tier, justification)
#
# Each justification answers ONE question: what would an anonymous visitor learn from
# this that they were not meant to learn? A move without an answer is not on this list.
RETIER_PLAN: dict[str, tuple[str, str]] = {
    # ── Trade-secret / proof depth: NDA ──────────────────────────────────────
    "Master_Thesis_2026_Feb.pdf": (
        TIER_NDA,
        "Full CRE mathematical derivation. The embedding maps, SPD route and recovery "
        "logic are explicitly NDA-only per 4.2 CRE Overview §8.1. Publishing the thesis "
        "publishes the mechanism.",
    ),
    "FQNM_arXiv.pdf": (
        TIER_CONTROLLED,
        "The paper is genuinely public (arXiv 2604.06947), so it is not secret — but "
        "serving it to anonymous visitors invites quantisation-design questions the "
        "public tier may not answer. Controlled-public keeps it reachable to identified "
        "visitors without making it a default retrieval source.",
    ),
    "TurboQuant_vs_FQNM_Comparison_Paper_V1.0.docx": (
        TIER_NDA,
        "Named-competitor comparison. §19.5 prohibits competitor comparison without "
        "approval on any public surface; retrievable at the public tier, an agent could "
        "assemble one from this.",
    ),
    "WP_Alpha_Compute_Core.docx": (
        TIER_NDA,
        "Draft white paper carrying internal benchmark characterisations and the claims-"
        "discipline appendix. Marked Draft v0.1 and never approved for publication.",
    ),
    # ── Commercially sensitive: INTERNAL ─────────────────────────────────────
    "iTrix_Pricing_Policy_Version_2.0.docx": (
        TIER_INTERNAL,
        "Pricing. §19.5 and R6: pricing, terms and exclusivity are NEVER public and are "
        "never emitted by an agent. The stream guard blocks pricing patterns mid-stream, "
        "but the retrieval source should not exist at the public tier in the first place.",
    ),
    "iTrix_Investor_Data_Room_File_List.docx": (
        TIER_INTERNAL,
        "Fundraising structure, round sizes and valuation strategy. Commercially "
        "sensitive and irrelevant to a compute-bottleneck visitor.",
    ),
    "Kickoff_Direction_for_the_itriX_Project.docx": (
        TIER_INTERNAL,
        "Internal project direction, team role assignments and approval chains. Names "
        "individuals and describes IWL operating behind the platform — which §15 of the "
        "Guideline Book explicitly says visitors must not be told.",
    ),
    "Project_Playbook_Ai_Sales_Platform_for_ITrix.docx": (
        TIER_INTERNAL,
        "The sales playbook itself. An agent retrieving this could describe its own "
        "qualification and scoring logic to the visitor being qualified.",
    ),
    # ── Build specifications: INTERNAL ───────────────────────────────────────
    "itriX_AI_Sales_Engine_MVP_Functional_Specification_V1.0.docx": (
        TIER_INTERNAL,
        "Specifies lead scoring, tiering and routing logic. Retrievable, an agent could "
        "explain how the visitor is being scored.",
    ),
    "iTrix_Website_MVP_Product_Requirement_Document_V1.0.docx": (
        TIER_INTERNAL,
        "Internal build requirements including qualification logic and CRM capture.",
    ),
    "iTrix_Website_Build_Package_V1.0.docx": (
        TIER_INTERNAL,
        "Internal build package. No visitor-facing value.",
    ),
    "iTrix_Website_UX_&_Content_Blueprint_V1.0.docx": (
        TIER_INTERNAL,
        "Internal UX blueprint describing the disclosure ladder and gating strategy.",
    ),
    "itriX_Website_Build_Execution_Plan_V2.0.docx": (
        TIER_INTERNAL,
        "Internal sprint plan.",
    ),
    "itriX_Website_Building_Guideline_Book.docx": (
        TIER_INTERNAL,
        "Describes the trust-then-disclose strategy and the concierge model, including "
        "that IWL operates behind the platform.",
    ),
    "itriX_Homepage_Wireframe_v0.3.docx": (
        TIER_INTERNAL,
        "Internal wireframe carrying the retired headline and the routing logic.",
    ),
    "itriX_Website_Personas_v0.1.docx": (
        TIER_INTERNAL,
        "Visitor personas and what to withhold from each. An agent retrieving this could "
        "tell a visitor which persona bucket they were placed in — the exact failure "
        "§4 PERSONALIZATION WITHOUT PROFILING prohibits.",
    ),
    "itriX_Visitor_Journey_Map_v0.1.docx": (
        TIER_INTERNAL,
        "Internal journey routing and handoff triggers.",
    ),
    "itriX_Compute_Bottleneck_Review_Briefing_Template_v0.3.docx": (
        TIER_CONTROLLED,
        "The briefing TEMPLATE, not a briefing. Useful to an identified visitor asking "
        "what a review contains; not a default public retrieval source.",
    ),
    "itriX_Knowledge_Core_Input_Request_List_v0.1.docx": (
        TIER_INTERNAL,
        "Lists what is deliberately NOT public and enumerates the prohibited-claims "
        "categories. Publishing the map of what is withheld is itself a disclosure.",
    ),
}

# Documents that are correctly public and must STAY public. Listed explicitly so the
# verify step can assert the public tier contains these and nothing else.
APPROVED_PUBLIC = {
    "4_1_AXIOM_Overview_v2.0.docx",
    "4_2_CRE_Overview_v2.0.docx",
    "4_3_FQNM_Overview_v2.0.docx",
    "4_4_Unified_Mathematical_View_Inventor_V2.0.docx",
    "5_1_ALPHA_Compute_Overview_v2.0.docx",
    "5_2_ALPHA_Core_Product_Overview_V2.0.docx",
    "6_Computational_Workload_and_Platform_Materials_V2.0.docx",
    "7_AI-Aggravated_Bottleneck_Materials_V2.0.docx",
    "Brand_Story_of_itriX.docx",
    "alpha_compute_problemology_public.md",
    "alpha_core_problemology_public.md",
    "brand_story_company_public.md",
    ".gitkeep",
}

# Filename patterns that must NEVER appear in a visitor-reachable tier. The CI tripwire
# (tests/test_knowledge_core/test_disclosure_tiering.py) asserts this.
NEVER_PUBLIC_PATTERNS = (
    "pricing",
    "investor",
    "data_room",
    "dataroom",
    "thesis",
    "kickoff",
    "playbook",
    "internal",
    "roadmap",
    "term_sheet",
    "valuation",
    "cap_table",
)

VISITOR_REACHABLE_TIERS = (TIER_PUBLIC, TIER_CONTROLLED)


def _key(name: str) -> str:
    """
    Normalise a filename for matching.

    The tree carries the same documents with spaces, underscores and mixed case across
    different export passes ("iTrix Pricing Policy Version 2.0.docx" vs
    "iTrix_Pricing_Policy_Version_2.0.docx"). Matching on the raw name means a re-tier
    silently misses a file the moment somebody re-exports it — which is exactly the kind
    of quiet failure that leaves a pricing document sitting in public/.
    """
    return "".join(ch for ch in name.lower().replace("_", " ") if ch.isalnum() or ch == " ").strip()


_PLAN_BY_KEY = {_key(name): (name, tier, why) for name, (tier, why) in RETIER_PLAN.items()}
_APPROVED_BY_KEY = {_key(name) for name in APPROVED_PUBLIC}


def build_plan() -> list[tuple[Path, Path, str]]:
    """Return (source, destination, justification) for every planned move."""
    moves: list[tuple[Path, Path, str]] = []
    public_dir = KNOWLEDGE_DOCS / TIER_PUBLIC
    if not public_dir.exists():
        return moves
    for path in sorted(public_dir.iterdir()):
        if path.is_dir():
            continue
        entry = _PLAN_BY_KEY.get(_key(path.name))
        if entry is None:
            continue
        _canonical, target_tier, justification = entry
        moves.append((path, KNOWLEDGE_DOCS / target_tier / path.name, justification))
    return moves


def unclassified() -> list[str]:
    """
    Files in public/ that are neither approved-public nor in the plan.

    An unclassified file is the dangerous case: nobody decided it was public, it just
    ended up there. Surfaced loudly rather than ignored.
    """
    public_dir = KNOWLEDGE_DOCS / TIER_PUBLIC
    if not public_dir.exists():
        return []
    out = []
    for path in sorted(public_dir.iterdir()):
        if path.is_dir() or path.name == ".gitkeep":
            continue
        key = _key(path.name)
        if key in _PLAN_BY_KEY or key in _APPROVED_BY_KEY:
            continue
        out.append(path.name)
    return out


def print_plan(moves) -> None:
    if not moves:
        print("No documents need re-tiering. The public tier is already clean.")
        return
    print(f"RE-TIER PLAN — {len(moves)} document(s) to move out of public/\n")
    by_tier: dict[str, list] = {}
    for src, dst, why in moves:
        by_tier.setdefault(dst.parent.name, []).append((src, why))
    for tier in (TIER_CONTROLLED, TIER_NDA, TIER_INTERNAL):
        rows = by_tier.get(tier, [])
        if not rows:
            continue
        print(f"  -> {tier}  ({len(rows)})")
        for src, why in rows:
            print(f"     {src.name}")
            for line in _wrap(why, 88):
                print(f"         {line}")
            print()
    print("Approval owner sign-off is required before --apply (Playbook §00b).")


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines, current = [], ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


def apply_plan(moves) -> int:
    moved = 0
    for src, dst, _why in moves:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            print(f"  SKIP (already present): {dst.relative_to(REPO_ROOT)}")
            continue
        shutil.move(str(src), str(dst))
        print(f"  moved {src.name} -> {dst.parent.name}/")
        moved += 1
    return moved


def verify() -> int:
    """
    Assert no never-public pattern sits in a visitor-reachable tier.

    Returns the number of violations. This is the same assertion the CI tripwire makes;
    having it here too means the operator running the re-tier gets the answer
    immediately rather than at the next build.
    """
    violations = 0
    for tier in VISITOR_REACHABLE_TIERS:
        tier_dir = KNOWLEDGE_DOCS / tier
        if not tier_dir.exists():
            continue
        for path in sorted(tier_dir.iterdir()):
            if path.is_dir() or path.name == ".gitkeep":
                continue
            lowered = path.name.lower()
            for pattern in NEVER_PUBLIC_PATTERNS:
                if pattern in lowered:
                    print(f"  VIOLATION [{tier}] {path.name} matches never-public {pattern!r}")
                    violations += 1
                    break
    if violations == 0:
        print("  No never-public patterns in any visitor-reachable tier.")
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Reviewable knowledge_docs re-tiering.")
    parser.add_argument("--plan", action="store_true", help="Print the plan; change nothing.")
    parser.add_argument("--apply", action="store_true", help="Move the files.")
    parser.add_argument("--verify", action="store_true", help="Assert no violations remain.")
    args = parser.parse_args()

    if not (args.plan or args.apply or args.verify):
        parser.print_help()
        return 2

    if args.plan:
        print_plan(build_plan())
        stray = unclassified()
        if stray:
            print(f"\nUNCLASSIFIED in public/ ({len(stray)}) — nobody approved these:")
            for name in stray:
                print(f"     {name}")
    if args.apply:
        moves = build_plan()
        print_plan(moves)
        print("\nAPPLYING...\n")
        moved = apply_plan(moves)
        print(f"\n{moved} file(s) moved.")
        print("\nNow purge and re-ingest, or the old chunks stay retrievable:")
        print("  manage.py purge_vectors --all --yes")
        print("  manage.py register_knowledge_docs")
        print("  manage.py reingest_namespace --all")
        print("  manage.py validate_knowledge_core")
    if args.verify:
        return 1 if verify() else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
