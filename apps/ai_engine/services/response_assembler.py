"""
Response assembler.

Normalises whatever the model returns into the strict result-section dict the result_page
builders expect, and runs every visitor-facing string through the hallucination guard
(claims discipline + grounding). It accepts either a JSON object (preferred — we ask the
model for JSON) or free text (used as the problem-mirror narrative), and always returns a
well-formed, safe partial that result_page can merge with its deterministic sections.

── v4.0.5 PARSE HARDENING ────────────────────────────────────────────────────
The model sometimes wraps its JSON in a ```json fence, adds a language tag, or emits a
short preamble before the object. The previous fence-stripping left a leading newline so
the object never parsed, and the whole raw JSON string was dumped into ``problemMirror``
(the page then showed a blob of escaped JSON). ``_coerce_json`` now: strips fences
correctly, removes a leading ``json`` tag, and — as a last resort — extracts the first
balanced ``{...}`` object from the text. If the parsed object itself nests the real
payload under a ``problemMirror`` key (i.e. the model double-wrapped), we unwrap it.
"""

from __future__ import annotations

import json
import logging
import re

from apps.ai_engine.services.hallucination_guard import guard

logger = logging.getLogger("itrix")


def _safe(text: str, evidence: str) -> str:
    return guard(text or "", evidence=evidence).text


def _extract_first_json_object(text: str) -> str | None:
    """Return the first balanced {...} block in text, or None."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return None


def _coerce_json(raw: str) -> dict | None:
    if not raw:
        return None
    cleaned = raw.strip()

    # Strip a leading ```/```json fence and any trailing fence.
    if cleaned.startswith("```"):
        # Drop the first line (``` or ```json) and a trailing ``` if present.
        cleaned = re.sub(r"^```[a-zA-Z0-9]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    # Remove a stray leading language tag (e.g. "json\n{...}").
    cleaned = re.sub(r"^json\s*", "", cleaned, flags=re.IGNORECASE).strip()

    # First attempt: parse as-is.
    for candidate in (cleaned, _extract_first_json_object(cleaned)):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(data, dict):
            # Unwrap a double-wrapped payload: {"problemMirror": "{...full json...}"}.
            pm = data.get("problemMirror")
            if isinstance(pm, str) and pm.strip().startswith("{") and "diagnosis" in pm:
                try:
                    inner = json.loads(pm)
                    if isinstance(inner, dict):
                        return inner
                except Exception:  # noqa: BLE001
                    pass
            return data
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
        # Treat the whole thing as the problem-mirror narrative — but never dump raw JSON.
        text = raw_response or ""
        if text.strip().startswith("{"):
            # Looks like JSON we failed to parse; don't show a blob to the visitor.
            logger.warning("assemble: model returned unparseable JSON-like text; omitting narrative")
            return partial
        safe_text = _safe(text, evidence)
        if safe_text:
            partial["problemMirror"] = safe_text
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
