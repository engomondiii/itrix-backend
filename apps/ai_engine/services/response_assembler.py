"""
Response assembler.

Normalises whatever the model returns into the strict result-section dict the result_page
builders expect, and runs every visitor-facing string through the hallucination guard
(claims discipline + grounding). It accepts either a JSON object (preferred — we ask the
model for JSON) or free text (used as the problem-mirror narrative), and always returns a
well-formed, safe partial that result_page can merge with its deterministic sections.
"""

from __future__ import annotations

import json
import logging

from apps.ai_engine.services.hallucination_guard import guard

logger = logging.getLogger("itrix")


def _safe(text: str, evidence: str) -> str:
    return guard(text or "", evidence=evidence).text


def _coerce_json(raw: str) -> dict | None:
    if not raw:
        return None
    cleaned = raw.strip()
    # Strip markdown fences if the model added them.
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None


def assemble(raw_response: str, *, evidence: str = "") -> dict:
    """
    Convert a model response into a safe partial result dict.

    Returns keys that overlap the ResultPage contract:
    ``problemMirror``, ``alphaFitSummary``, ``diagnosis`` (list), ``kpiPreview`` (list),
    ``recommendedNextStep``. Any missing key is simply omitted so result_page fills it.
    """
    data = _coerce_json(raw_response)
    partial: dict = {}

    if data is None:
        # Treat the whole thing as the problem-mirror narrative.
        text = _safe(raw_response, evidence)
        if text:
            partial["problemMirror"] = text
        return partial

    if "problemMirror" in data:
        partial["problemMirror"] = _safe(str(data["problemMirror"]), evidence)
    if "alphaFitSummary" in data:
        partial["alphaFitSummary"] = _safe(str(data["alphaFitSummary"]), evidence)
    if "recommendedNextStep" in data:
        partial["recommendedNextStep"] = _safe(str(data["recommendedNextStep"]), evidence)

    if isinstance(data.get("diagnosis"), list):
        rows = []
        for row in data["diagnosis"]:
            if not isinstance(row, dict):
                continue
            rows.append(
                {
                    "pressure": row.get("pressure", ""),
                    "observation": _safe(str(row.get("observation", "")), evidence),
                    "itrixInterpretation": _safe(str(row.get("itrixInterpretation", "")), evidence),
                    "alphaRole": _safe(str(row.get("alphaRole", "")), evidence),
                }
            )
        if rows:
            partial["diagnosis"] = rows

    if isinstance(data.get("kpiPreview"), list):
        kpis = []
        for kpi in data["kpiPreview"]:
            if isinstance(kpi, dict) and kpi.get("label"):
                kpis.append(
                    {"label": str(kpi["label"]), "metric": _safe(str(kpi.get("metric", "")), evidence)}
                )
        if kpis:
            partial["kpiPreview"] = kpis

    return partial
