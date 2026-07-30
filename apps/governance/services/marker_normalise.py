"""
THE MARKER-NORMALISED SECOND PASS (Architecture v2.8 §19.9 rule 5, Backend v7.1 Phase 2).

── WHY A SECOND PASS EXISTS AT ALL ─────────────────────────────────────────

The stream guard matches prohibited patterns against the raw token buffer. That was
sufficient while assistant text was rendered as plain paragraphs. It stops being
sufficient the moment the surface renders Markdown, because markup can split a pattern
past a matcher that only ever sees raw characters:

    gua*ran*tee        renders as:  guarantee
    **guarantee**      renders as:  guarantee
    `$3M`              renders as:  $3M
    [guarantee](#x)    renders as:  guarantee
    gua\\*ran\\*tee      renders as:  gua*ran*tee   -> normalises to guarantee
    | 40 | % |         renders as:  40 %

Every one of those is the exact string the guard exists to stop, and every one of them
passes a raw-text match. The visitor reads the prohibited claim; the guard reports
nothing.

So THE GUARD MATCHES EVERY BUFFER TWICE — once raw, once marker-stripped — before any
parse and before any token reaches a client.

── THIS IS THE PRECONDITION FOR THE FRONTEND FLAG ──────────────────────────
``NEXT_PUBLIC_ENABLE_MARKDOWN_TURNS`` must not be enabled until this pass is live. That
is an ordering constraint rather than a preference: turning on Markdown rendering first
would widen what a prohibited pattern can hide behind, and the widening would be
invisible because the guard would keep reporting clean.

``itrix-web/src/lib/markdown/normalizeMarkers.ts`` MIRRORS this module. It exists there
for tests and for a development warning ONLY — the enforcement is here, on the server,
because a client-side filter would be the client deciding what the visitor may read.

── WHAT NORMALISATION DELIBERATELY DOES NOT DO ─────────────────────────────
It does not try to render Markdown. It strips the syntax that could hide a pattern and
leaves everything else alone, because a renderer would be a second, subtly different
implementation of the frontend's parser — and a mismatch between them is exactly the gap
an evasion lives in. Stripping is a superset: anything the renderer would show, the
stripped text contains.
"""

from __future__ import annotations

import re

# ─────────────────────────────────────────────────────────────────────────────
# The strip pipeline. ORDER MATTERS.
# ─────────────────────────────────────────────────────────────────────────────
# 1) Backslash escapes FIRST, via a SENTINEL.
#
#    An escaped delimiter renders as the LITERAL CHARACTER: `10x fa\*st\*er` displays as
#    `10x fa*st*er`, asterisks and all — which does NOT match `\d+\s?x faster`, so it is
#    not an evasion and must not be treated as one.
#
#    A first version of this stripped the backslash and let the delimiter pass through to
#    step 4, which removed the asterisk too and produced `10x faster` — a FALSE HALT on
#    text that renders harmlessly. A guard that cries wolf is a guard someone disables, so
#    the escaped character is parked on a sentinel that survives the delimiter sweep and is
#    restored afterwards.
#
#    The escaped character is ENCODED — sentinel, its ordinal in decimal, sentinel — rather
#    than merely marked. Marking it is not enough: a sentinel sitting BESIDE an asterisk does
#    not stop step 4 removing the asterisk, which was the first attempt at this and did not
#    work. The character has to leave the string and come back.
#
#    U+E000 is the first Private Use Area codepoint. Step 6's invisible-character sweep runs
#    BEFORE this, and any pre-existing sentinel is removed explicitly, so an input cannot
#    smuggle one in to protect a delimiter from the sweep.
_SENTINEL = "\ue000"
_ESCAPES = re.compile(r"\\([\\`*_{}\[\]()#+\-.!>~|])")
_ENCODED = re.compile(_SENTINEL + r"(\d+)" + _SENTINEL)

# 2) Links and images: keep the visible LABEL, drop the URL. The label is what a reader
#    sees, so it is the label a prohibited pattern would hide in.
_INLINE_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_REF_LINK = re.compile(r"!?\[([^\]]*)\]\[[^\]]*\]")

# 3) Autolinks: <https://…> renders as the URL itself.
_AUTOLINK = re.compile(r"<((?:https?|mailto):[^>]+)>")

# 4) Delimiters and table pipes. Code spans, emphasis, strikethrough.
_DELIMITERS = re.compile(r"[`*_~|]")

# 5) Leading block markers, per line: blockquotes, headings, list bullets and numbers.
#    Applied REPEATEDLY to a fixed point, because they nest: "> ## guarantee" is a
#    heading inside a blockquote, and one pass would leave "## guarantee" with the
#    heading marker still attached. A single pass was the first version of this and it
#    let that case through.
_BLOCK_MARKERS = re.compile(r"^[ \t]*(?:>+[ \t]*|#{1,6}[ \t]+|[-+*][ \t]+|\d+\.[ \t]+)", re.MULTILINE)

# 7) Horizontal whitespace runs, collapsed to one space.
#    THIS IS NOT COSMETIC. Stripping table pipes turns "| 40 | % |" into " 40  % ", and
#    the pricing rule is `\d{1,3}\s?%` — one optional space. Two spaces defeat it, so a
#    prohibited figure laid out as a table row would pass both matcher passes.
#    Newlines are preserved: they are a real boundary, and collapsing them would join
#    unrelated lines into strings that never render.
_HSPACE_RUNS = re.compile(r"[ \t]{2,}")

# 6) Zero-width and bidirectional characters. Not Markdown, but the same class of
#    evasion: U+200B between letters splits a word for a matcher while rendering as
#    nothing at all, and a bidi override can make rendered text read in a different
#    order from the text that was matched.
_INVISIBLES = re.compile(r"[\u200b-\u200d\ufeff\u202a-\u202e\u2066-\u2069\u200e\u200f\u061c]")


def normalise_markers(text: str) -> str:
    """
    Strip Markdown syntax so the remaining text reads as it will be RENDERED.

    Length is NOT preserved — the returned string is shorter than the input, so a match
    position in the normalised text does not map back to the raw buffer. Callers that
    need a position must use the raw pass; callers that need to know WHETHER something
    prohibited will be rendered use this one. ``stream_guard`` reports the raw position
    when it has one and 0 otherwise, and that is honest about what it knows.
    """
    if not text:
        return ""

    out = _INVISIBLES.sub("", text)
    # Any pre-existing sentinel is removed first, so an input cannot smuggle one in and
    # protect a delimiter from the sweep.
    out = out.replace(_SENTINEL, "")
    out = _ESCAPES.sub(lambda m: f"{_SENTINEL}{ord(m.group(1))}{_SENTINEL}", out)
    out = _INLINE_LINK.sub(r"\1", out)
    out = _REF_LINK.sub(r"\1", out)
    out = _AUTOLINK.sub(r"\1", out)
    out = _DELIMITERS.sub("", out)

    # To a fixed point: block markers nest. Bounded so a pathological input cannot spin.
    for _ in range(8):
        stripped = _BLOCK_MARKERS.sub("", out)
        if stripped == out:
            break
        out = stripped

    # Restore the escaped characters from their ordinals.
    out = _ENCODED.sub(lambda m: chr(int(m.group(1))), out)
    # Any unpaired sentinel is dropped rather than left visible.
    out = out.replace(_SENTINEL, "")
    return _HSPACE_RUNS.sub(" ", out)


def differs(text: str) -> bool:
    """
    True when normalisation changed anything.

    Used to skip the second matcher pass on the overwhelmingly common case of plain
    prose. The check is a string comparison against work already done, so it costs one
    comparison and saves a full pattern sweep per token.
    """
    return normalise_markers(text) != (text or "")
