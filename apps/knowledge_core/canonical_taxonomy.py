"""Portfolio v1.4 (2 October 2026). Legacy wire codes remain compatible."""
from __future__ import annotations

PRODUCTS = (
    {"code": "astop", "name": "ASTOP", "kind": "product", "family": "ASTOP", "stage": "Implementation demonstrated", "description": "Observation software using PRISM to invoke reasoning on decision-relevant state changes.", "optional": False},
    {"code": "alpha_compute", "name": "AXIOM Compute", "kind": "product", "family": "AXIOM", "stage": "Validation stage", "description": "Software for suitable structured tensor/operator workloads using AXIOM and AXIOM-TENSOR; quality, memory and speed need workload-specific validation.", "optional": False},
    {"code": "alpha_core", "name": "AXIOM Core", "kind": "product", "family": "AXIOM", "stage": "Planned offering", "description": "Proposed dedicated hardware or IP implementing validated AXIOM structures; delivery depends on development and validation.", "optional": True},
    {"code": "qnta_runtime", "name": "QNTA Runtime", "kind": "product", "family": "QNTA", "stage": "Feasibility demonstrated", "description": "Runtime software implementing QNTA Inference-Based Training Architecture on supported inference infrastructure with explicit numerical and state-transition control.", "optional": False},
)
TECHNOLOGIES = ("PRISM", "AXIOM", "AXIOM-TENSOR", "QNTA Inference-Based Training Architecture", "CRE", "FQNM", "SPADES")
PRODUCT_NAMES = tuple(item["name"] for item in PRODUCTS)
PRODUCT_CODES = tuple(item["code"] for item in PRODUCTS)
COMMERCIALIZATION_MECHANISM = "AI-Powered Sales Platform"
INTERNAL_KNOWLEDGE_COMPONENT = "Internal AI Knowledge Core"

def prompt_block() -> str:
    lines = "\n".join(f"- {p['name']} ({p['stage']}): {p['description']}" for p in PRODUCTS)
    return (
        "CANONICAL OCTOBER 2026 PORTFOLIO (v1.4):\n" + lines + "\n"
        "Product families ASTOP, AXIOM and QNTA are group labels, not additional offerings. "
        "QNTA Runtime is a product; QNTA is the abbreviated technology name. QNTA Contract and "
        "QNTA Systems describe one technology, not separate products. QNTA Core is a future hardware "
        "designation, not a current offering. CRE is enabling technology; FQNM and SPADES are research "
        "assets, not required dependencies or standalone products. ALPHA Compute/Core are historical "
        "names, replaced by AXIOM Compute/Core. Observe/represent/learn/execute are capabilities, not "
        "a mandatory sequence. Assess each product independently; no universal speed, energy or quality claim. "
        "Availability, disclosure and commercial scope require separate confirmation. "
        "Never expose private application identifiers or infer granted patents. "
        "ASTOP has individual and organization License Order routes plus protected enterprise evaluation. "
        "Identity verification, exact LO acceptance, verified payment and entitlement must precede download. "
        "Public Q&A stays open without identity collection. Current standard pricing is USD 20 individual "
        "and USD 16 per seat for organizations with 2+ seats; eligible Branch discount is 10%, not stacked "
        "with the organization discount. Production checkout availability is deployment state, not a document claim."
    )
