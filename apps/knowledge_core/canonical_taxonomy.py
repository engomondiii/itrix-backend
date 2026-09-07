"""Canonical September 2026 itriX product/technology taxonomy.

This module is deliberately data-only.  It is the repository-level source used by
system-prompt construction, hard-fact synchronization and Knowledge validation so those
surfaces cannot drift into slightly different catalogues.

Entity type and evidence status are separate axes: being a product says nothing about
whether a workload has been validated, value-verified or made licensable.
"""
from __future__ import annotations

PRODUCTS: tuple[dict[str, str | bool], ...] = (
    {
        "code": "astop",
        "name": "ASTOP",
        "kind": "product",
        "description": "Observation product that operationalizes the PRISM observation domain.",
        "optional": False,
    },
    {
        "code": "alpha_compute",
        "name": "ALPHA Compute",
        "kind": "product",
        "description": "Independent software computational infrastructure product for eligible workloads.",
        "optional": False,
    },
    {
        "code": "alpha_core",
        "name": "ALPHA Core",
        "kind": "product",
        "description": "Separate optional hardware product, considered only when validated software-layer evidence justifies deeper hardware implementation or acceleration.",
        "optional": True,
    },
)

TECHNOLOGIES: tuple[str, ...] = (
    "PRISM",
    "AXIOM",
    "AXIOM-TENSOR",
    "CRE",
    "FQNM",
    "QNTA",
)

PRODUCT_NAMES: tuple[str, ...] = tuple(str(item["name"]) for item in PRODUCTS)
PRODUCT_CODES: tuple[str, ...] = tuple(str(item["code"]) for item in PRODUCTS)

COMMERCIALIZATION_MECHANISM = "AI-Powered Sales Platform"
INTERNAL_KNOWLEDGE_COMPONENT = "Internal AI Knowledge Core"


def prompt_block() -> str:
    """Return a compact deterministic taxonomy block for model system prompts."""
    product_lines = "\n".join(
        f"- {item['name']}: {item['description']}" for item in PRODUCTS
    )
    technology_lines = "\n".join(f"- {name}" for name in TECHNOLOGIES)
    return (
        "CANONICAL SEPTEMBER 2026 TAXONOMY (entity type is deterministic):\n"
        "PRODUCTS — the complete currently sold product catalogue:\n"
        f"{product_lines}\n"
        "TECHNOLOGIES — these are NOT separately sold products:\n"
        f"{technology_lines}\n"
        f"COMMERCIALIZATION MECHANISM: {COMMERCIALIZATION_MECHANISM}.\n"
        "Do not list PRISM, AXIOM, AXIOM-TENSOR, CRE, FQNM or QNTA as products. "
        "Do not omit ASTOP from an explicit complete product catalogue. "
        "ASTOP and ALPHA are technically independent; commercial sequencing does not imply technical dependency. "
        "Entity type is not evidence status: 'product' does not mean validated, value-verified, licensable or applicable to a particular workload."
    )
