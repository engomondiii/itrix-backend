"""Deterministic confidential-input interception for public conversation planes.

The control distinguishes *disclosure of potentially restricted material* from an
ordinary policy question that merely contains words such as ``confidential`` or ``NDA``.
When it fires, the raw visitor turn is still retained as the user's own record, but it is
not sent to retrieval/model orchestration and is not repeated in the assistant reply.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Numeric specifications paired with obvious internal/unreleased vocabulary catch the
# adversarial test shape without treating every public benchmark number as confidential.
_SPEC = re.compile(
    r"\b(?:unreleased|internal|confidential|proprietary|not public|secret|prototype|roadmap)\b"
    r".{0,160}\b\d+(?:\.\d+)?\s*(?:w|watts?|tflops?|pflops?|tops?|gb|tb|ghz|mhz|ms|us|ns|%)\b",
    re.I | re.S,
)
_IDENTIFIER = re.compile(
    r"\b(?:unreleased|internal|confidential|proprietary|prototype|codename)\b.{0,80}"
    r"\b(?-i:[A-Z][A-Z0-9_-]{3,})\b",
    re.I | re.S,
)

# A sensitive noun is not enough by itself: the surrounding turn must indicate that the
# visitor is supplying / possessing / about to supply the material.  This avoids blocking
# questions such as "How do you handle confidential information?".
_SENSITIVE_NOUN = (
    r"(?:confidential|proprietary|unreleased|unpublished|not[- ]public|trade secret|"
    r"internal benchmark|source code|architecture diagram|exact algorithm|exact implementation|"
    r"chip design|rtl|netlist|kernel implementation|solver internals|model weights|training data)"
)
_DISCLOSURE = re.compile(
    rf"(?:\b(?:our|my)\b.{{0,80}}\b{_SENSITIVE_NOUN}\b|"
    rf"\b{_SENSITIVE_NOUN}\b.{{0,80}}\b(?:we|i|our|my)\b|"
    rf"\b(?:i(?:'m| am)?\s+(?:sharing|sending|giving|providing|pasting)|"
    rf"we(?:'re| are)?\s+(?:sharing|sending|giving|providing)|"
    rf"here(?:'s| is)|these are|the following is)\b.{{0,100}}\b{_SENSITIVE_NOUN}\b)",
    re.I | re.S,
)
_SENSITIVE_PHRASES = re.compile(
    r"\b(?:under nda|do not share|internal only|our secret|our source code|our architecture diagram|"
    r"our exact algorithm|our exact implementation|our chip design|our rtl|our netlist|"
    r"our kernel implementation|our solver internals|our model weights|our training data)\b",
    re.I,
)
_PROSPECTIVE_NONDISCLOSURE = re.compile(
    rf"\b(?:before|without)\s+(?:i|we)\s+(?:disclose|share|provide|send|paste)\b.{{0,80}}\b{_SENSITIVE_NOUN}\b|"
    rf"\bbefore\s+(?:disclosing|sharing|providing|sending|pasting)\b.{{0,80}}\b{_SENSITIVE_NOUN}\b",
    re.I | re.S,
)


@dataclass(frozen=True)
class Intercept:
    sensitive: bool
    reason: str = ""


def detect(text: str) -> Intercept:
    raw = text or ""
    # Concrete unreleased values/identifiers always win, even if the turn also says
    # "before I share".  Otherwise a prospective boundary statement is exactly the
    # safe behavior we want to encourage and is not itself a disclosure.
    if _SPEC.search(raw) or _IDENTIFIER.search(raw):
        return Intercept(True, "unreleased_specification")
    if _PROSPECTIVE_NONDISCLOSURE.search(raw):
        return Intercept(False, "")
    if _SENSITIVE_PHRASES.search(raw) or _DISCLOSURE.search(raw):
        return Intercept(True, "confidentiality_signal")
    return Intercept(False, "")


def safe_reply(*, locale: str = "en") -> str:
    if (locale or "").lower().startswith("ko"):
        return (
            "이 채널에서는 기밀·미공개 기술 세부정보를 계속 처리하지 않겠습니다. "
            "방금 공유한 식별자나 수치도 반복하거나 분석에 사용하지 않겠습니다. "
            "지금은 비기밀 수준으로 문제를 다시 표현해 주세요. 실제 기밀 자료가 필요한 경우에는 "
            "승인된 NDA/보안 경로를 먼저 사용해야 합니다."
        )
    return (
        "I’m going to stop substantive processing of that technical detail here because it may be "
        "confidential or unreleased. I won’t repeat the identifiers or figures you supplied, and I "
        "won’t build an analysis on them in this public channel. Please restate the problem at a "
        "non-confidential level; if the actual material is needed, use the approved NDA/secure path first."
    )
