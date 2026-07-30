"""
What the running build believes the instrument versions are (Backend v7.1 §15.1).

── THE VERSIONS ARE A DEPLOYMENT FACT ──────────────────────────────────────
They come from the environment, because a hotfix to the wording that did not move the
version would leave every subsequent assent pointing at a document nobody read.

``GET legal/instruments/`` serves this, and `itrix-web`'s `useLegalAssent` compares it
against what IT renders. A mismatch is not cosmetic: it means every assent being recorded
right now is attached to a version the visitor did not see. The frontend warns in
development rather than adapting, because reconciling the two is a human decision.

── NOTHING HERE SERVES THE INSTRUMENT TEXT ─────────────────────────────────
Only slugs, versions and effective dates. The text lives in `itrix-web`'s
`lib/content/legalCopy.ts` and is rendered from there.

That looks like a duplication and is the opposite. If the backend served the text, there
would be two publication paths for a legal document — the repo and the API — and the one
that shipped last would win silently. One publisher, and this endpoint exists so the other
side can notice when they disagree.
"""

from __future__ import annotations

import logging

from django.conf import settings

from apps.legal.constants import INSTRUMENT_SLUGS, INSTRUMENT_TITLES

logger = logging.getLogger("itrix")

# Slug -> the settings keys holding its version and effective date.
_SETTINGS_KEYS: dict[str, tuple[str, str]] = {
    "terms": ("LEGAL_TERMS_VERSION", "LEGAL_TERMS_EFFECTIVE"),
    "privacy": ("LEGAL_PRIVACY_VERSION", "LEGAL_PRIVACY_EFFECTIVE"),
    "security": ("LEGAL_SECURITY_VERSION", "LEGAL_SECURITY_EFFECTIVE"),
    "disclosure-policy": ("LEGAL_DISCLOSURE_VERSION", "LEGAL_DISCLOSURE_EFFECTIVE"),
}


def published() -> bool:
    """
    Whether the instruments have been signed off by counsel.

    Defaults FALSE. Until it is true the routes still answer — a visitor must always be able
    to read what governs their use — but the payload says `published: false`, and
    `itrix-web` renders the draft banner and a `noindex`. An unreviewed Terms of Service
    presented as authoritative is worse than a delayed one.
    """
    return bool(getattr(settings, "LEGAL_PUBLISHED", False))


def version_of(slug: str) -> str:
    keys = _SETTINGS_KEYS.get(slug)
    if keys is None:
        return ""
    return str(getattr(settings, keys[0], "") or "")


def effective_of(slug: str) -> str:
    keys = _SETTINGS_KEYS.get(slug)
    if keys is None:
        return ""
    return str(getattr(settings, keys[1], "") or "")


def all_instruments() -> list[dict]:
    """Every instrument, in the canonical order, with its version and effective date."""
    return [
        {
            "slug": slug,
            "title": INSTRUMENT_TITLES[slug],
            "version": version_of(slug),
            "effective": effective_of(slug),
        }
        for slug in INSTRUMENT_SLUGS
    ]


def current_versions(slugs) -> list[dict]:
    """
    The version entries for ``slugs``, ready to store on an assent record.

    Raises ``ValueError`` on an unknown slug or a missing version. Both are refusals rather
    than defaults, and for the same reason: an assent record naming an instrument the
    platform does not publish, or naming version "" , is unverifiable — you cannot go and
    read what was agreed to. Storing it would create evidence that proves nothing while
    looking like it proves something, which is worse than having none.
    """
    out: list[dict] = []
    for slug in slugs:
        if slug not in INSTRUMENT_SLUGS:
            raise ValueError(f"'{slug}' is not a published itriX legal instrument.")
        version = version_of(slug)
        if not version:
            raise ValueError(
                f"No version configured for '{slug}'. An assent record naming version '' "
                "is unverifiable — set LEGAL_*_VERSION before taking assent."
            )
        out.append({"slug": slug, "version": version, "effective": effective_of(slug)})
    return out
