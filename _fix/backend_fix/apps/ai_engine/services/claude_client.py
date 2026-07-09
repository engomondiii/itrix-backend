"""
Claude client.

A thin, defensive wrapper over the Anthropic Messages API. The anthropic SDK is imported
lazily and only used when ``ENABLE_AI_ENGINE`` is on and a key is present. Callers should
treat ``complete`` as best-effort: when the engine is disabled (Phase 2 default) it raises
``AIEngineDisabled`` so callers fall back to their deterministic path.

── HANG-PROOFING (v4.0.1) ────────────────────────────────────────────────────
Every call is bounded by a hard wall-clock timeout and a small retry cap, so a slow or
stalled model call can never tie up a web worker (Railway gunicorn kills workers at
120 s). The timeout is read from ``AI_CALL_TIMEOUT_SECONDS`` (default 20 s) and applied
both at the client level and per request. On timeout/any error we raise
``AIEngineDisabled`` so the caller degrades to its deterministic path immediately.
"""

from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger("itrix")


class AIEngineDisabled(RuntimeError):
    """Raised when an AI call is attempted while the engine is disabled / unconfigured."""


def _timeout_seconds() -> float:
    """Hard wall-clock timeout for a single Claude call (seconds)."""
    try:
        return float(getattr(settings, "AI_CALL_TIMEOUT_SECONDS", 20))
    except (TypeError, ValueError):
        return 20.0


def _max_retries() -> int:
    """SDK-level retry cap. Kept small so total latency stays well under the worker limit."""
    try:
        return int(getattr(settings, "AI_CALL_MAX_RETRIES", 1))
    except (TypeError, ValueError):
        return 1


class ClaudeClient:
    def __init__(self):
        self.enabled = settings.ENABLE_AI_ENGINE and bool(settings.ANTHROPIC_API_KEY)
        self.model = settings.ANTHROPIC_MODEL
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from anthropic import Anthropic  # noqa: PLC0415 - lazy

            # Bound the client so no single call can hang a web worker.
            self._client = Anthropic(
                api_key=settings.ANTHROPIC_API_KEY,
                timeout=_timeout_seconds(),
                max_retries=_max_retries(),
            )
        return self._client

    def complete(self, *, system: str, user: str, max_tokens: int = 1024, temperature: float = 0.2) -> str:
        """Return Claude's text completion, or raise ``AIEngineDisabled`` when off/slow/failed."""
        if not self.enabled:
            raise AIEngineDisabled("AI engine disabled or ANTHROPIC_API_KEY missing.")
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": user}],
                # Belt-and-braces: also bound this specific request.
                timeout=_timeout_seconds(),
            )
            parts = [block.text for block in resp.content if getattr(block, "type", "") == "text"]
            return "\n".join(parts).strip()
        except AIEngineDisabled:
            raise
        except Exception as exc:  # noqa: BLE001
            # Includes anthropic.APITimeoutError — treat every failure as "degrade now".
            logger.warning("Claude completion failed/timed out (%s); using fallback.", type(exc).__name__)
            raise AIEngineDisabled(str(exc)) from exc
