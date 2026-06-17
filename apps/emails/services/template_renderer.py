"""
Template renderer.

Renders ``{{variable}}`` placeholders in a template body against a context dict. Used by
the email builders and reusable by templates_library. Intentionally tiny and dependency-free
(no Django template engine needed) so it works on plain strings from the DB.
"""

from __future__ import annotations

import re

_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


def render(template: str, context: dict) -> str:
    """Replace {{var}} with context[var]; unknown vars render as empty strings."""
    if not template:
        return ""

    def _sub(match: re.Match) -> str:
        key = match.group(1)
        value = context.get(key, "")
        return "" if value is None else str(value)

    return _VAR_RE.sub(_sub, template)


def extract_variables(template: str) -> list[str]:
    """Return the unique ordered list of {{variable}} names in a template."""
    seen: list[str] = []
    for match in _VAR_RE.finditer(template or ""):
        name = match.group(1)
        if name not in seen:
            seen.append(name)
    return seen
