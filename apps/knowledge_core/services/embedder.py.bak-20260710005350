"""
Embedder.

Turns chunk text into embedding vectors via OpenAI when ``ENABLE_AI_ENGINE`` is on. When
the AI engine is disabled (Phase 2 default) it returns **deterministic pseudo-embeddings**
derived from a hash of the text, so the ingestion pipeline runs end-to-end — chunks get a
stable vector and a vector id — without any API key. The dimension matches the configured
embedding model so a later real re-ingest is a drop-in.

Deterministic vectors are clearly not semantically meaningful; they exist so the pipeline,
the DB records, and the upsert path are all exercised and demoable offline.
"""

from __future__ import annotations

import hashlib
import logging
import struct

from django.conf import settings

logger = logging.getLogger("itrix")

# text-embedding-3-small = 1536 dims; -3-large = 3072. Default to small.
_MODEL_DIMS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


def embedding_dimension() -> int:
    return _MODEL_DIMS.get(settings.OPENAI_EMBEDDING_MODEL, 1536)


def _deterministic_vector(text: str, dim: int) -> list[float]:
    """A stable unit-norm pseudo-vector seeded from the text (offline stand-in)."""
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    # Expand the 32-byte digest into `dim` floats in [-1, 1] deterministically.
    values: list[float] = []
    counter = 0
    while len(values) < dim:
        block = hashlib.sha256(seed + struct.pack(">I", counter)).digest()
        for i in range(0, len(block), 4):
            if len(values) >= dim:
                break
            (n,) = struct.unpack(">I", block[i : i + 4])
            values.append((n / 0xFFFFFFFF) * 2.0 - 1.0)
        counter += 1
    # Normalise to unit length (cosine-friendly).
    norm = sum(v * v for v in values) ** 0.5 or 1.0
    return [v / norm for v in values]


class Embedder:
    def __init__(self):
        self.dim = embedding_dimension()
        self.enabled = settings.ENABLE_AI_ENGINE and bool(settings.OPENAI_API_KEY)
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI  # noqa: PLC0415 - lazy

            self._client = OpenAI(api_key=settings.OPENAI_API_KEY)
        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Return one vector per input text.

        Retries the OpenAI call a few times with exponential backoff so a transient network
        blip or rate-limit doesn't silently drop a chunk to a deterministic vector. Only after
        all retries are exhausted do we fall back (and log loudly).
        """
        if not texts:
            return []
        if not self.enabled:
            return [_deterministic_vector(t, self.dim) for t in texts]

        import time

        last_exc = None
        for attempt in range(4):  # up to 4 tries: 0s, ~1s, ~2s, ~4s
            try:
                resp = self.client.embeddings.create(
                    model=settings.OPENAI_EMBEDDING_MODEL, input=texts
                )
                return [item.embedding for item in resp.data]
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < 3:
                    wait = 2 ** attempt
                    logger.warning(
                        "OpenAI embedding attempt %d/4 failed (%s); retrying in %ss…",
                        attempt + 1, type(exc).__name__, wait,
                    )
                    time.sleep(wait)

        logger.error(
            "OpenAI embedding failed after retries; falling back to deterministic vectors: %s",
            last_exc,
        )
        return [_deterministic_vector(t, self.dim) for t in texts]

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


def embed_texts(texts: list[str]) -> list[list[float]]:
    return Embedder().embed(texts)
