"""
Slug utilities.

Wraps python-slugify and adds a uniqueness helper used when, e.g., naming knowledge
document folders (Phase 2) or any model that needs a stable, collision-free slug.
"""

from __future__ import annotations

from typing import Callable

from slugify import slugify as _slugify


def slugify_text(value: str, *, max_length: int = 80) -> str:
    """Return a lowercase, URL-safe slug, bounded to ``max_length``."""
    return _slugify(value or "", max_length=max_length) or "item"


def unique_slug(
    value: str,
    *,
    exists: Callable[[str], bool],
    max_length: int = 80,
) -> str:
    """
    Produce a slug that does not already exist.

    ``exists(slug)`` should return True if the slug is taken. Appends ``-2``, ``-3``,
    … until a free slug is found.
    """
    base = slugify_text(value, max_length=max_length)
    if not exists(base):
        return base
    suffix = 2
    while True:
        candidate = f"{base[: max_length - len(str(suffix)) - 1]}-{suffix}"
        if not exists(candidate):
            return candidate
        suffix += 1
