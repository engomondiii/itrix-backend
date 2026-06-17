"""
License-path explainer.

Turns the routed commercial pathway code into the web's display value
(``LicensePathway | null``) and a short, guardrailed explanation. Exclusive / strategic
pathways always carry a "subject to review" note, consistent with reserved-rights discipline.
"""

from __future__ import annotations

_DISPLAY = {
    "non_exclusive": "Non-Exclusive",
    "exclusive": "Exclusive",
    "strategic": "Strategic",
}

_EXPLANATION = {
    "non_exclusive": "A non-exclusive license lets you use the technology without reserving it from others.",
    "exclusive": "An exclusive license reserves a defined field or scope — available subject to review and NDA.",
    "strategic": "A strategic arrangement covers exclusivity at scale — available subject to executive review and NDA.",
}


def license_display(commercial_path: str | None) -> str | None:
    if not commercial_path:
        return None
    return _DISPLAY.get(commercial_path.lower())


def license_explanation(commercial_path: str | None) -> str:
    if not commercial_path:
        return "You indicated product use rather than licensing; we can revisit licensing anytime."
    return _EXPLANATION.get(commercial_path.lower(), "")
