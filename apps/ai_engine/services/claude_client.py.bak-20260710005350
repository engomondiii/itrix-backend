"""
Claude client.

A thin, defensive wrapper over the Anthropic Messages API. The anthropic SDK is imported
lazily and only used when ``ENABLE_AI_ENGINE`` is on and a key is present. Callers should
treat ``complete`` as best-effort: when the engine is disabled (Phase 2 default) it raises
``AIEngineDisabled`` so callers fall back to their deterministic path.
"""

from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger("itrix")


class AIEngineDisabled(RuntimeError):
    """Raised when an AI call is attempted while the engine is disabled / unconfigured."""


class ClaudeClient:
    def __init__(self):
        self.enabled = settings.ENABLE_AI_ENGINE and bool(settings.ANTHROPIC_API_KEY)
        self.model = settings.ANTHROPIC_MODEL
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from anthropic import Anthropic  # noqa: PLC0415 - lazy

            self._client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        return self._client

    def complete(self, *, system: str, user: str, max_tokens: int = 1024, temperature: float = 0.2) -> str:
        """Return Claude's text completion, or raise ``AIEngineDisabled`` when off."""
        if not self.enabled:
            raise AIEngineDisabled("AI engine disabled or ANTHROPIC_API_KEY missing.")
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            parts = [block.text for block in resp.content if getattr(block, "type", "") == "text"]
            return "\n".join(parts).strip()
        except AIEngineDisabled:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Claude completion failed")
            raise AIEngineDisabled(str(exc)) from exc
