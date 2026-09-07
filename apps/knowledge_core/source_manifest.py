"""Explicit source governance for significant Knowledge Core documents.

Filenames are identifiers here, not authority signals.  A word such as ``canonical`` or
``executed`` in a filename never grants authority by itself.  The manifest records only
sources whose precedence/currentness needs an explicit governed decision; unlisted files
fall back to conservative working-source metadata in the registration command.
"""
from __future__ import annotations

from dataclasses import dataclass


class ClaimDomain:
    TAXONOMY = "taxonomy_product_identity"
    COMMERCIALIZATION = "commercialization_gtm"
    PUBLIC_EXPLANATION = "public_product_explanation"
    TECHNICAL = "technical_capability"
    RESEARCH = "research_evidence"
    LEGAL = "legal_contract"
    INTERNAL_POLICY = "internal_policy"


@dataclass(frozen=True)
class SourcePolicy:
    authority: str
    current: bool
    canonical_rule: str = ""
    claim_domains: tuple[str, ...] = ()
    supersedes: tuple[str, ...] = ()
    superseded_by: str = ""
    prohibited_messages: tuple[str, ...] = ()


SOURCE_MANIFEST: dict[str, SourcePolicy] = {
    # Current taxonomy / public explanation.
    "itrix_product_canonical_v3_5.md": SourcePolicy(
        "authoritative", True,
        "Current September 2026 public product/technology taxonomy",
        (ClaimDomain.TAXONOMY, ClaimDomain.PUBLIC_EXPLANATION),
        ("itrix_product_canonical_v2_4.md", "WP_ALPHA_Compute_Core_v2.4.docx"),
    ),
    "itrix_company_overview_public.md": SourcePolicy(
        "governing", True,
        "Current public company/product explanation; subordinate to the canonical taxonomy for entity identity",
        (ClaimDomain.PUBLIC_EXPLANATION, ClaimDomain.TAXONOMY),
    ),
    "astop_prism_public_safe_v2_3.md": SourcePolicy(
        "governing", True,
        "Approved public-safe ASTOP/PRISM explanation bounded by current GTM and evidence",
        (ClaimDomain.PUBLIC_EXPLANATION, ClaimDomain.TECHNICAL, ClaimDomain.RESEARCH),
        prohibited_messages=("ASTOP is self-service", "Public executable/download entitlement"),
    ),
    # Current primary / governing September sources.
    "itriX_White_Paper_v3.5.docx": SourcePolicy(
        "authoritative", True,
        "Current canonical product/technology taxonomy and evidence boundaries",
        (ClaimDomain.TAXONOMY, ClaimDomain.TECHNICAL, ClaimDomain.RESEARCH),
        ("WP_ALPHA_Compute_Core_v2.4.docx",),
    ),
    "PRISM_and_ASTOP_Explained.docx": SourcePolicy(
        "governing", True,
        "Current controlled explanation of the PRISM-to-ASTOP relationship",
        (ClaimDomain.PUBLIC_EXPLANATION, ClaimDomain.TECHNICAL, ClaimDomain.RESEARCH),
    ),
    "prism-paper-current_v2.pdf": SourcePolicy(
        "authoritative", True,
        "Current PRISM primary research evidence within its demonstrated scope",
        (ClaimDomain.RESEARCH, ClaimDomain.TECHNICAL),
    ),
    "ASTOP_Productization_GTM_Plan_v2.3.docx": SourcePolicy(
        "authoritative", True,
        "September 2026 governing ASTOP commercialization source",
        (ClaimDomain.COMMERCIALIZATION, ClaimDomain.INTERNAL_POLICY),
        prohibited_messages=("ASTOP is self-service", "Public checkout or uncontrolled production binaries"),
    ),
    "itriX_AI_Sales_Platform_MVP_Guide_for_Fidel_v3.5.docx": SourcePolicy(
        "authoritative", True,
        "September 2026 governing Sales Platform progression/waiver behavior",
        (ClaimDomain.COMMERCIALIZATION, ClaimDomain.INTERNAL_POLICY),
    ),
    "ASTOP_Technical_Capabilities_Current_v0.3.1.md": SourcePolicy(
        "governing", True,
        "Current controlled ASTOP technical capability synthesis",
        (ClaimDomain.TECHNICAL,),
    ),
    "AXIOM_TENSOR_QNTA_Current_Controlled.md": SourcePolicy(
        "governing", True,
        "Current controlled AXIOM-TENSOR/QNTA technical synthesis",
        (ClaimDomain.TECHNICAL, ClaimDomain.RESEARCH),
    ),
    "itriX_MVP_Acceptance_Rerun_Feedback_to_Fidel.docx": SourcePolicy(
        "governing", True,
        "Latest targeted MVP acceptance corrections",
        (ClaimDomain.INTERNAL_POLICY,),
    ),
    "iTrix Pricing Policy Version 2.0.docx": SourcePolicy(
        "governing", True,
        "Internal commercial policy only; not visitor product doctrine",
        (ClaimDomain.INTERNAL_POLICY, ClaimDomain.COMMERCIALIZATION),
    ),
    "licensing_and_commercialization_internal.md": SourcePolicy(
        "governing", True,
        "Internal licensing/commercialization policy; never public disclosure authority",
        (ClaimDomain.INTERNAL_POLICY, ClaimDomain.COMMERCIALIZATION),
    ),
    # Historical source history retained but explicitly non-current.
    "itrix_product_canonical_v2_4.md": SourcePolicy(
        "legacy", False,
        "Superseded ALPHA-only product taxonomy retained for source history",
        (ClaimDomain.TAXONOMY,),
        superseded_by="itrix_product_canonical_v3_5.md",
    ),
    "WP_ALPHA_Compute_Core_v2.4.docx": SourcePolicy(
        "legacy", False,
        "Superseded pre-ASTOP ALPHA product doctrine retained for source history",
        (ClaimDomain.TAXONOMY, ClaimDomain.TECHNICAL),
        superseded_by="itriX_White_Paper_v3.5.docx",
    ),
    "README_Astop.txt": SourcePolicy(
        "legacy", False,
        "Superseded commercialization/distribution assumptions; technical details require current approved synthesis",
        (ClaimDomain.COMMERCIALIZATION, ClaimDomain.TECHNICAL),
        superseded_by="ASTOP_Productization_GTM_Plan_v2.3.docx",
        prohibited_messages=("GitHub Releases are the current commercial distribution route", "ASTOP is self-service"),
    ),
    # Pre-September commercial / website doctrine retained only as historical project evidence.
    # These documents are useful for tracing how the MVP evolved, but several contain
    # ALPHA-only catalogues, direct-ALPHA routing, or conversion assumptions that the
    # September v3.5/v2.3 sources explicitly replaced. They must never compete in
    # current Knowledge retrieval.
    "Project Playbook_Ai Sales Platform for ITrix.docx": SourcePolicy(
        "legacy", False,
        "Pre-September AI-sales playbook; superseded for product taxonomy and commercial progression",
        (ClaimDomain.TAXONOMY, ClaimDomain.COMMERCIALIZATION, ClaimDomain.INTERNAL_POLICY),
        superseded_by="itriX_AI_Sales_Platform_MVP_Guide_for_Fidel_v3.5.docx",
    ),
    "Kickoff Direction for the itriX Project.docx": SourcePolicy(
        "legacy", False,
        "Historical kickoff direction; superseded by current September taxonomy/GTM",
        (ClaimDomain.TAXONOMY, ClaimDomain.COMMERCIALIZATION),
        superseded_by="itriX_AI_Sales_Platform_MVP_Guide_for_Fidel_v3.5.docx",
    ),
    "itriX AI Sales Engine MVP Functional Specification_V1.0.docx": SourcePolicy(
        "legacy", False,
        "Historical ALPHA-era sales-engine specification",
        (ClaimDomain.TAXONOMY, ClaimDomain.COMMERCIALIZATION, ClaimDomain.INTERNAL_POLICY),
        superseded_by="itriX_AI_Sales_Platform_MVP_Guide_for_Fidel_v3.5.docx",
    ),
    "itriX_AI_Sales_Engine_Master_Architecture_Flow_Document_v1.0 (1).docx": SourcePolicy(
        "legacy", False,
        "Historical sales-engine architecture flow superseded by current Sales Platform doctrine",
        (ClaimDomain.COMMERCIALIZATION, ClaimDomain.INTERNAL_POLICY),
        superseded_by="itriX_AI_Sales_Platform_MVP_Guide_for_Fidel_v3.5.docx",
    ),
    "itriX_AI_Sales_Engine_MVP_Execution_Milestone_Operations_Command_v1.0 (1).docx": SourcePolicy(
        "legacy", False,
        "Historical MVP execution doctrine superseded by current Sales Platform progression",
        (ClaimDomain.COMMERCIALIZATION, ClaimDomain.INTERNAL_POLICY),
        superseded_by="itriX_AI_Sales_Platform_MVP_Guide_for_Fidel_v3.5.docx",
    ),
    "iTrix Website MVP Product Requirement Document_V1.0.docx": SourcePolicy(
        "legacy", False,
        "Historical website MVP product doctrine; not current product/GTM authority",
        (ClaimDomain.TAXONOMY, ClaimDomain.PUBLIC_EXPLANATION, ClaimDomain.COMMERCIALIZATION),
        superseded_by="itriX_AI_Sales_Platform_MVP_Guide_for_Fidel_v3.5.docx",
    ),
    "iTrix Website UX & Content Blueprint_V1.0.docx": SourcePolicy(
        "legacy", False,
        "Historical website UX/content blueprint; not current product/GTM authority",
        (ClaimDomain.PUBLIC_EXPLANATION, ClaimDomain.COMMERCIALIZATION),
        superseded_by="itriX_AI_Sales_Platform_MVP_Guide_for_Fidel_v3.5.docx",
    ),
    "iTrix Website Build Package_V1.0.docx": SourcePolicy(
        "legacy", False,
        "Historical website build package; not current product/GTM authority",
        (ClaimDomain.PUBLIC_EXPLANATION, ClaimDomain.COMMERCIALIZATION),
        superseded_by="itriX_AI_Sales_Platform_MVP_Guide_for_Fidel_v3.5.docx",
    ),
    "itriX Website Build Execution Plan_V2.0.docx": SourcePolicy(
        "legacy", False,
        "Historical website execution plan; current Sales Platform/GTM sources govern progression",
        (ClaimDomain.COMMERCIALIZATION, ClaimDomain.INTERNAL_POLICY),
        superseded_by="itriX_AI_Sales_Platform_MVP_Guide_for_Fidel_v3.5.docx",
    ),
    "itriX Visitor Journey Map v0.1.docx": SourcePolicy(
        "legacy", False,
        "Historical visitor-journey model superseded by the current governed journey architecture",
        (ClaimDomain.PUBLIC_EXPLANATION, ClaimDomain.COMMERCIALIZATION),
        superseded_by="itriX_MVP_Acceptance_Rerun_Feedback_to_Fidel.docx",
    ),
    "itriX Website Personas v0.1.docx": SourcePolicy(
        "legacy", False,
        "Historical public persona/routing assumptions; current visitor treatment is purpose-led",
        (ClaimDomain.PUBLIC_EXPLANATION, ClaimDomain.INTERNAL_POLICY),
        superseded_by="itriX_MVP_Acceptance_Rerun_Feedback_to_Fidel.docx",
    ),
    "itriX Website Building Guideline Book.docx": SourcePolicy(
        "legacy", False,
        "Historical ALPHA-era website/product guidance; current September sources govern product identity and progression",
        (ClaimDomain.TAXONOMY, ClaimDomain.PUBLIC_EXPLANATION, ClaimDomain.COMMERCIALIZATION),
        superseded_by="itriX_AI_Sales_Platform_MVP_Guide_for_Fidel_v3.5.docx",
    ),
    "itriX Homepage Wireframe v0.3.docx": SourcePolicy(
        "legacy", False,
        "Historical homepage wireframe retained for design history, not current product doctrine",
        (ClaimDomain.PUBLIC_EXPLANATION,),
        superseded_by="itriX_MVP_Acceptance_Rerun_Feedback_to_Fidel.docx",
    ),
    "iTrix Investor Data Room File List.docx": SourcePolicy(
        "legacy", False,
        "Historical diligence-file blueprint containing pre-ASTOP product narrative; not current portfolio authority",
        (ClaimDomain.TAXONOMY, ClaimDomain.INTERNAL_POLICY),
        superseded_by="itriX_White_Paper_v3.5.docx",
    ),
    "6_Computational Workload and Platform Materials_V2.0.docx": SourcePolicy(
        "legacy", False,
        "Historical ALPHA-era platform-routing material; current product progression is governed by September sources",
        (ClaimDomain.TECHNICAL, ClaimDomain.PUBLIC_EXPLANATION),
        superseded_by="itriX_White_Paper_v3.5.docx",
    ),
    "7_AI-Aggravated Bottleneck Materials_V2.0.docx": SourcePolicy(
        "legacy", False,
        "Historical ALPHA-era routing material; retained for source history",
        (ClaimDomain.TECHNICAL, ClaimDomain.PUBLIC_EXPLANATION),
        superseded_by="itriX_White_Paper_v3.5.docx",
    ),
    "4_1_AXIOM_Overview_v2.0.docx": SourcePolicy(
        "working", True,
        "Supporting AXIOM technical material only; current product identity/routing is governed by v3.5 taxonomy/GTM",
        (ClaimDomain.TECHNICAL, ClaimDomain.RESEARCH),
        prohibited_messages=("Treat ALPHA-era routing language as current product qualification",),
    ),
    "4_2_CRE_Overview_v2.0.docx": SourcePolicy(
        "working", True,
        "Supporting CRE technical material only; current product identity/routing is governed by v3.5 taxonomy/GTM",
        (ClaimDomain.TECHNICAL, ClaimDomain.RESEARCH),
        prohibited_messages=("Treat ALPHA-era routing language as current product qualification",),
    ),
    "4_3_FQNM_Overview_v2.0.docx": SourcePolicy(
        "working", True,
        "Supporting FQNM technical material only; current product identity/routing is governed by v3.5 taxonomy/GTM",
        (ClaimDomain.TECHNICAL, ClaimDomain.RESEARCH),
        prohibited_messages=("Treat ALPHA-era routing language as current product qualification",),
    ),
    "4_4_Unified Mathematical View_Inventor_V2.0.docx": SourcePolicy(
        "working", True,
        "Supporting mathematical synthesis only; current product identity/routing is governed by v3.5 taxonomy/GTM",
        (ClaimDomain.TECHNICAL, ClaimDomain.RESEARCH),
        prohibited_messages=("Treat ALPHA-era product-boundary language as current product qualification",),
    ),
}


def policy_for(filename: str) -> SourcePolicy | None:
    """Return explicit policy using case-insensitive basename matching."""
    folded = filename.casefold()
    for name, policy in SOURCE_MANIFEST.items():
        if name.casefold() == folded:
            return policy
    return None
