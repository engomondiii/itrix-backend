"""
The HTML alternative for outbound mail — so links are CLICKABLE.

── WHY THIS EXISTS (fix, 2026-08-12) ────────────────────────────────────────
Every builder produces plain text, and every message went out as `text/plain` only.
Most clients auto-detect a bare URL, but not all of them do it reliably: Outlook
desktop breaks long URLs across lines and then linkifies only the first fragment, and
several corporate clients strip auto-detection entirely. The reported symptom was the
confirmation link arriving as dead text — and a confirmation link that cannot be
clicked is a workspace nobody can finish opening.

The fix is a `multipart/alternative` message: the plain-text body stays exactly as it
is and remains the canonical version, with an HTML alternative generated FROM it.

── THE TEXT REMAINS THE SOURCE OF TRUTH ─────────────────────────────────────
Nothing here writes copy. The HTML is a rendering of the same string the builders
already produce and the same string `EmailLog.body` records, so there is no second
place where wording can drift, and an auditor reading the log sees what was sent.

── ESCAPE FIRST, THEN LINKIFY ───────────────────────────────────────────────
Order matters and is the whole safety story. The text is HTML-escaped before any
anchor is inserted, so a body containing `<b>` or `"` cannot introduce markup, and
the only tags in the output are the ones this module puts there. Linkifying first and
escaping afterwards would destroy the anchors; escaping first and linkifying the
escaped text is safe because `&amp;` inside an href is correct HTML and every browser
and mail client resolves it back to `&`.
"""

from __future__ import annotations

import html
import re

# http(s) URLs only. Deliberately NOT `www.`-style bare hosts: guessing a scheme for
# something that merely looks like a host is how a sentence fragment becomes a link.
#
# Runs greedily to whitespace and then trims trailing sentence punctuation, rather than
# excluding those characters from the match. A capability token is `<payload>.<signature>`
# and CONTAINS a period, so a pattern that stopped at a dot would cut the link in half —
# the same trap the transcript's client-page button was written to avoid.
_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

# Trailing characters that belong to the sentence, not the URL.
_TRAILING = re.compile(r"[.,;:!?)\]}'\"]+$")

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+", re.IGNORECASE)


def _anchor(href: str, label: str) -> str:
    return f'<a href="{href}" style="color:#1F2937;text-decoration:underline;">{label}</a>'


def linkify(escaped_text: str) -> str:
    """
    Turn URLs and email addresses in ALREADY-ESCAPED text into anchors.

    Exported for its own tests: this is the part where a mistake would either break a
    link or introduce markup, so it is asserted directly rather than only through the
    assembled message.
    """

    def replace_url(match: re.Match[str]) -> str:
        raw = match.group(0)
        trailing = ""
        trimmed = _TRAILING.sub("", raw)
        if len(trimmed) < len(raw):
            trailing = raw[len(trimmed):]
        # `&amp;` is how an escaped `&` appears; it is valid in an href and is what the
        # client resolves. The label shows the same string, so the visible URL and the
        # destination cannot differ — a link whose text says one host and whose href
        # says another is the shape of a phishing mail.
        return _anchor(trimmed, trimmed) + trailing

    linked = _URL.sub(replace_url, escaped_text)

    def replace_email(match: re.Match[str]) -> str:
        address = match.group(0)
        return _anchor(f"mailto:{address}", address)

    # Applied after URLs, and only to text that is not already inside an anchor we just
    # made — an address inside a URL's query string must not be re-wrapped.
    parts = re.split(r"(<a [^>]*>.*?</a>)", linked, flags=re.DOTALL)
    return "".join(part if part.startswith("<a ") else _EMAIL.sub(replace_email, part) for part in parts)


def html_from_text(body: str) -> str:
    """
    A minimal HTML alternative for a plain-text email body.

    Inline styles only, and few of them. A stylesheet is stripped by most clients and a
    layout table is a maintenance burden for a message that is four sentences long; what
    matters here is that the link is a link and the paragraphs keep their breaks.
    """
    escaped = html.escape(body or "", quote=True)
    linked = linkify(escaped)
    paragraphs = [block.strip() for block in re.split(r"\n\s*\n", linked) if block.strip()]
    rendered = "".join(
        f'<p style="margin:0 0 16px 0;">{block.replace(chr(10), "<br />")}</p>'
        for block in paragraphs
    )
    return (
        '<div style="font-family:Inter,Helvetica,Arial,sans-serif;font-size:15px;'
        'line-height:1.6;color:#1F2937;max-width:560px;">'
        f"{rendered}"
        "</div>"
    )
