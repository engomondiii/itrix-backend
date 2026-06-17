"""
NDA checklist.

The standard pre-disclosure checklist attached to a new NDA record. Mirrors the kind of
gating the exclusive-approval flow expects before detailed (nda_only) disclosure.
"""

from __future__ import annotations

NDA_CHECKLIST_ITEMS = [
    "Counterparty legal entity confirmed",
    "Mutual NDA template selected",
    "Scope of disclosure defined",
    "Signatory identified on both sides",
    "NDA sent for signature",
    "Signed NDA received and filed",
]


def default_checklist() -> list[dict]:
    return [{"id": i + 1, "label": text, "done": False} for i, text in enumerate(NDA_CHECKLIST_ITEMS)]
