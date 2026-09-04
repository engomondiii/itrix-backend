"""Deterministic outbound policy for conversation text.

Prompts remain useful for style and reasoning; these are the boundaries a model does not
get to decide.  The policy is intentionally narrow and auditable rather than a general
rewriter.
"""
from __future__ import annotations

import re

_FALSE_MEMORY = re.compile(
    r"(?:^|(?<=[.!?]\s))(?:as (?:i|we) (?:said|mentioned) (?:earlier|before)|"
    r"you (?:asked|said|told me) (?:this |that )?before|we (?:already )?(?:agreed|decided)|"
    r"your nda is (?:already )?signed)[^.!?]*[.!?]?\s*",
    re.I,
)

# Known source-authority corrections. These are safe because the current project source
# explicitly records applications / preprint status; no generated identifier is inserted.
_HARD_FACT_REPLACEMENTS = (
    (re.compile(r"\bthree granted korean patents\b", re.I), "three Korean patent applications"),
    (re.compile(r"\bgranted korean patents\b", re.I), "Korean patent applications"),
    (re.compile(r"\bpeer[- ]reviewed arxiv (?:paper|preprint)\b", re.I), "arXiv preprint"),
    (re.compile(r"\bpeer reviewed arxiv (?:paper|preprint)\b", re.I), "arXiv preprint"),
)

_RECOMMENDATION_SENTENCE = re.compile(
    r"(?:(?<=^)|(?<=[.!?]\s))[^.!?]*(?:we recommend|i recommend|recommended(?: route| path| next step)?|"
    r"the best (?:route|path|next step)|you should (?:start|begin|use|choose)|"
    r"your next step (?:is|should be)|we(?:'d| would) begin with (?:an? )?(?:alpha|representation review)|"
    r"start (?:an? )?(?:alpha compute|representation review|proof path|poc|proof-of-concept))[^.!?]*[.!?]?\s*",
    re.I,
)


def enforce(text: str, *, thread=None) -> str:
    out = text or ""
    out = _FALSE_MEMORY.sub("", out)
    for pattern, replacement in _HARD_FACT_REPLACEMENTS:
        out = pattern.sub(replacement, out)

    if thread is not None:
        try:
            from apps.conversations.services import engagement_state

            # STR-03 / STR-05 hard gate. Factual explanation of a product remains allowed;
            # only prescriptive route/next-step language is removed before confirmation.
            if engagement_state.is_customer(thread) and not engagement_state.recommendation_allowed(thread):
                out = _RECOMMENDATION_SENTENCE.sub("", out)
        except Exception:
            pass

        # Before execution, customer-facing legal/commercial outcomes remain conditional.
        if getattr(thread, "contract_stage", "no_discussion") != "executed":
            out = re.sub(r"\byou are entitled to\b", "the agreement would need to state whether you may receive", out, flags=re.I)
            out = re.sub(r"\bsublicensing (?:is|defaults to) (?:not permitted|no)\b", "sublicensing would need to be agreed", out, flags=re.I)
            out = re.sub(r"\bsilence is not permission\b", "the agreement should address that point explicitly", out, flags=re.I)
            out = re.sub(r"\bpublication (?:is|will be) prohibited\b", "publication treatment would need to be agreed", out, flags=re.I)

    return " ".join(out.split()) if "\n" not in out else "\n".join(line.rstrip() for line in out.splitlines()).strip()
