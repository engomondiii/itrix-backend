"""
Outbound terminology normalisation — internal names never reach a visitor.

── WHY THIS EXISTS (change request, 2026-08-10) ──────────────────────────────
"Knowledge Core" is the INTERNAL name for the AXIOM/CRE/FQNM stack. The public
name is "itriX Technologies". The name leaked into live conversations because
the system prompt itself used it and every retrieved knowledge document does
too. The prompt now teaches the public name (system_prompt_builder), which is
the primary fix; this module is the deterministic guarantee — the same shape as
the reveal-link and contact-ask appends: even if the model repeats what a
retrieved document says, the persisted, delivered reply does not carry the
internal name.

The mapping deliberately swallows a leading article: "the Knowledge Core is"
reads as "itriX Technologies is", not "the itriX Technologies is". A brand name
that begins with a lowercase letter starts sentences that way by design — that
is the mark's casing, not a typo (see brand.wordmark on the frontend).

Scope: AGENT-authored conversation replies only. Visitor and team messages are
never rewritten — they are what a person actually wrote, and rewriting a
human's words would falsify the record.
"""

from __future__ import annotations

import re

# The internal name, with or without a leading article, in any casing, tolerant
# of arbitrary whitespace (a streamed reply can wrap mid-phrase). Word-bounded on
# both sides so nothing composite ("knowledge cores of ...") half-matches.
_INTERNAL_STACK_NAME = re.compile(r"\b(?:the\s+)?knowledge\s+core\b", re.IGNORECASE)

PUBLIC_STACK_NAME = "itriX Technologies"


def normalise_outbound(text: str) -> str:
    """Replace internal terminology with the public name in an agent reply."""
    if not text:
        return text
    return _INTERNAL_STACK_NAME.sub(PUBLIC_STACK_NAME, text)
