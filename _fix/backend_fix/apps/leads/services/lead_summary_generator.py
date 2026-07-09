"""
Lead summary generator.

Produces the short, internal "compute bottleneck" summary shown on the lead and the
``GET leads/{id}/summary/`` endpoint. When the AI engine is enabled it *can* ask Claude
for a crisp summary; otherwise it composes a clear, deterministic summary from the prompt,
pressure areas, and routed product — so the field is always populated, with no AI
dependency in Phase 2's default configuration.

── HANG-PROOFING (v4.0.1) ────────────────────────────────────────────────────
Lead creation runs on the SYNCHRONOUS qualify request path. A Claude call here was a
hidden blocking dependency that (with AI on) could push the qualify response toward the
120 s gunicorn worker limit and hang /review/preparing. The AI summary is therefore now
OPT-IN: by default (``LEAD_SUMMARY_USE_AI`` unset/false) ``generate_lead_summary`` returns
the deterministic summary instantly. The AI path still exists for background/offline use
(pass ``allow_ai=True`` explicitly, or set ``LEAD_SUMMARY_USE_AI=True``), and the Claude
client itself is now hard-timeout-bounded regardless.

All output respects claims discipline (no guarantees / superlatives).
"""

from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger("itrix")

_PRESSURE_PHRASE = {
    "cost": "compute cost growth",
    "speed": "slow turnaround",
    "energy": "power/cooling limits",
    "stability_accuracy": "stability or accuracy drift at scale",
    "memory_data_movement": "data-movement-bound runtime",
    "hardware_utilization": "underused accelerators",
    "architecture": "architectural ceiling",
}

_ROUTE_PHRASE = {
    "alpha_compute": "Representation-level diagnosis (ALPHA Compute) is the natural entry point.",
    "alpha_core": "Execution/runtime work (ALPHA Core) is the natural entry point.",
    "both": "Both representation (ALPHA Compute) and execution (ALPHA Core) are relevant.",
    "general": "A general ALPHA review is the natural entry point.",
}


def _deterministic_summary(*, prompt: str, pressures: list[str], product_route: str) -> str:
    pains = [_PRESSURE_PHRASE.get(p) for p in (pressures or []) if p in _PRESSURE_PHRASE]
    pain_str = ", ".join([p for p in pains if p]) or "a compute bottleneck"
    base = prompt.strip()
    if len(base) > 280:
        base = base[:277].rstrip() + "…"
    route_str = _ROUTE_PHRASE.get(product_route, _ROUTE_PHRASE["general"])
    if base:
        return f"Visitor reports {pain_str}. In their words: “{base}”. {route_str}"
    return f"Visitor reports {pain_str}. {route_str}"


def generate_lead_summary(
    *,
    prompt: str,
    pressures: list[str],
    product_route: str,
    tier: int,
    allow_ai: bool | None = None,
) -> str:
    """
    Return a concise internal summary of the lead's bottleneck.

    By default this is fully deterministic and instant (safe on the synchronous request
    path). The AI path is used only when explicitly allowed — either ``allow_ai=True`` or
    the ``LEAD_SUMMARY_USE_AI`` setting is truthy — AND the engine is enabled.
    """
    if allow_ai is None:
        allow_ai = bool(getattr(settings, "LEAD_SUMMARY_USE_AI", False))

    if not (allow_ai and settings.ENABLE_AI_ENGINE):
        return _deterministic_summary(prompt=prompt, pressures=pressures, product_route=product_route)

    # AI path — kept defensive: any failure falls back to the deterministic summary. The
    # Claude client carries a hard timeout, so this cannot hang even when opted in.
    try:
        from apps.ai_engine.services.claude_client import ClaudeClient

        client = ClaudeClient()
        system = (
            "You summarise a prospective customer's compute bottleneck for an internal "
            "sales CRM in 2–3 sentences. Be concrete and neutral. Never promise specific "
            "savings or use superlatives; defer quantitative claims to a validated PoC."
        )
        user = (
            f"Prompt: {prompt}\nPressure areas: {', '.join(pressures or []) or 'none'}\n"
            f"Routed product: {product_route}\nTier: {tier}\n\nWrite the summary."
        )
        text = client.complete(system=system, user=user, max_tokens=220)
        return text.strip() or _deterministic_summary(
            prompt=prompt, pressures=pressures, product_route=product_route
        )
    except Exception:  # noqa: BLE001
        logger.warning("AI lead summary failed/timed out; using deterministic summary.")
        return _deterministic_summary(prompt=prompt, pressures=pressures, product_route=product_route)
