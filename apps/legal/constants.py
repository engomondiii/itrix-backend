"""
THE FOUR INSTRUMENTS (Architecture v2.8 §19.10, itriX Legal Instruments v1.1).

    terms               Terms of Service
    privacy             Privacy Policy
    security            Security Statement
    disclosure-policy   Disclosure Policy

── THE VERSIONS LIVE IN SETTINGS, NOT HERE ─────────────────────────────────
A version is a deployment fact: the running build serves a particular text, and the
assent record has to name the version that build showed. Hard-coding it in a module means
a hotfix to the wording ships without the version moving, and every assent recorded
afterwards points at a document nobody read.

So the slugs are closed here and the versions come from the environment. If they disagree
with what `itrix-web` renders, `audit_legal_versions` says so — that mismatch means every
assent being recorded is attached to a version the visitor did not read.

── WHY THE SET IS CLOSED ───────────────────────────────────────────────────
An assent record naming an instrument the platform does not publish is unverifiable: you
cannot go and read what was agreed to. So a POST naming an unknown slug is refused rather
than stored.
"""

from __future__ import annotations

SLUG_TERMS = "terms"
SLUG_PRIVACY = "privacy"
SLUG_SECURITY = "security"
SLUG_DISCLOSURE = "disclosure-policy"

INSTRUMENT_SLUGS: tuple[str, ...] = (SLUG_TERMS, SLUG_PRIVACY, SLUG_SECURITY, SLUG_DISCLOSURE)

INSTRUMENT_TITLES: dict[str, str] = {
    SLUG_TERMS: "Terms of Service",
    SLUG_PRIVACY: "Privacy Policy",
    SLUG_SECURITY: "Security Statement",
    SLUG_DISCLOSURE: "Disclosure Policy",
}

# ── WHICH INSTRUMENTS ASSENT BINDS ──────────────────────────────────────────
# Terms and Privacy only. Security and Disclosure are STATEMENTS: they describe what the
# platform does, and asking someone to "agree" to a description of our own security posture
# would be meaningless — there is no obligation on them to accept.
#
# Playbook v1.8 §18C's checkbox names exactly these two, and the two lists must not drift:
# a checkbox naming two instruments while the record stores four would make the record
# claim more than the visitor was shown.
ASSENT_REQUIRED_SLUGS: tuple[str, ...] = (SLUG_TERMS, SLUG_PRIVACY)


def is_instrument(slug: str) -> bool:
    return slug in INSTRUMENT_SLUGS
