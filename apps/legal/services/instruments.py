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
    Whether the configured legal instruments are currently published.

    Publication controls the legal status/version presented by the platform. It is independent
    of journey state, NDA state and content authorization.
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


def display_version_of(slug: str) -> str:
    """Version the public route is displaying right now.

    When publication is disabled, ``LEGAL_DRAFT_VERSION`` remains available as a safe
    compatibility display version. When published, the deployment-controlled effective version
    and effective date bind.
    """
    if not published():
        return str(getattr(settings, "LEGAL_DRAFT_VERSION", "1.2") or "1.2")
    return version_of(slug)


def all_instruments() -> list[dict]:
    """Every displayed instrument plus explicit publication state."""
    return [
        {
            "slug": slug,
            "title": INSTRUMENT_TITLES[slug],
            "version": display_version_of(slug),
            "effective": effective_of(slug) if published() else "",
            "published": published(),
        }
        for slug in INSTRUMENT_SLUGS
    ]


def current_versions(slugs) -> list[dict]:
    """
    The version entries for ``slugs``, ready to store on an assent/acknowledgement record.

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
        version = display_version_of(slug)
        if not version:
            raise ValueError(
                f"No display version configured for '{slug}'. An assent record naming version '' "
                "is unverifiable."
            )
        out.append({
            "slug": slug,
            "version": version,
            "effective": effective_of(slug) if published() else "",
            "published": published(),
        })
    return out
