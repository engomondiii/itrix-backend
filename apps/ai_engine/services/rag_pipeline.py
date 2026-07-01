"""
RAG pipeline — v4.0 COMPATIBILITY SHIM.

The RAG result pipeline has been generalized into the agent runtime: the retrieve →
prompt → Claude → assemble → guard flow now lives in
``apps.agents.services.diagnosis`` (the Diagnosis agent). This module is kept as a thin
shim so every existing import and test that referenced ``run_rag`` /
``generate_result_partial`` / ``RagResult`` keeps working byte-for-byte — the public
functions delegate to the Diagnosis agent, which reproduces the identical flow and the
same graceful degradation.

Prefer importing from ``apps.agents.services.diagnosis`` (or going through the agent
runtime) in new code; this shim exists purely for backwards compatibility.
"""

from __future__ import annotations

from apps.agents.services.diagnosis import RagResult, run_rag

__all__ = ["RagResult", "run_rag", "generate_result_partial"]


def generate_result_partial(**kwargs) -> dict:
    """Convenience wrapper returning just the safe partial dict (unchanged API)."""
    return run_rag(**kwargs).partial
