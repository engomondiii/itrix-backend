"""
Embedder.

Turns chunk text into embedding vectors via OpenAI when ``ENABLE_AI_ENGINE`` is on. When
the AI engine is disabled (Phase 2 default) it returns **deterministic pseudo-embeddings**
derived from a hash of the text, so the ingestion pipeline runs end-to-end — chunks get a
stable vector and a vector id — without any API key. The dimension matches the configured
embedding model so a later real re-ingest is a drop-in.

Deterministic vectors are clearly not semantically meaningful; they exist so the pipeline,
the DB records, and the upsert path are all exercised and demoable offline.

── HANG-PROOFING (v4.0.1) ────────────────────────────────────────────────────
The OpenAI client is created with a hard timeout + small retry cap. Retries no longer
sleep on the request path: ingestion (a batch/offline job) may retry a few times, but
single-query embedding used during a live request (``embed_one``) does at most one bounded
attempt before falling back to a deterministic vector, so a slow OpenAI call can never tie
up a web worker.
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


def _timeout_seconds() -> float:
    try:
        return float(getattr(settings, "AI_CALL_TIMEOUT_SECONDS", 20))
    except (TypeError, ValueError):
        return 20.0


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

            # Bound the client so no single embedding call can hang a web worker.
            self._client = OpenAI(
                api_key=settings.OPENAI_API_KEY,
                timeout=_timeout_seconds(),
                max_retries=0,  # we manage retries explicitly below (offline path only)
            )
        return self._client

    def _embed_once(self, texts: list[str]) -> list[list[float]]:
        resp = self.client.embeddings.create(model=settings.OPENAI_EMBEDDING_MODEL, input=texts)
        return [item.embedding for item in resp.data]

    def embed(self, texts: list[str], *, retries: int = 3, backoff: bool = True) -> list[list[float]]:
        """
        Return one vector per input text.

        ``retries``/``backoff`` are tuned for the OFFLINE ingestion path (a Celery/CLI job),
        where a transient blip should not drop a chunk to a deterministic vector. On the LIVE
        request path use ``embed_one`` (retries=0, no sleeps) so a slow OpenAI call cannot tie
        up a web worker.
        """
        if not texts:
            return []
        if not self.enabled:
            return [_deterministic_vector(t, self.dim) for t in texts]

        import time

        last_exc = None
        attempts = max(1, retries + 1)
        for attempt in range(attempts):
            try:
                return self._embed_once(texts)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < attempts - 1:
                    if backoff:
                        wait = 2 ** attempt
                        logger.warning(
                            "OpenAI embedding attempt %d/%d failed (%s); retrying in %ss…",
                            attempt + 1, attempts, type(exc).__name__, wait,
                        )
                        time.sleep(wait)
                    else:
                        logger.warning(
                            "OpenAI embedding attempt %d/%d failed (%s); retrying…",
                            attempt + 1, attempts, type(exc).__name__,
                        )

        logger.error(
            "OpenAI embedding failed after %d attempt(s); falling back to deterministic vectors: %s",
            attempts, last_exc,
        )
        return [_deterministic_vector(t, self.dim) for t in texts]

    def embed_one(self, text: str) -> list[float]:
        """
        Single-query embedding for the LIVE request path (RAG retrieval).

        Bounded and sleep-free: at most one attempt (plus the client's own hard timeout),
        then a deterministic fallback. This guarantees retrieval can never stall a request.
        """
        return self.embed([text], retries=0, backoff=False)[0]


def embed_texts(texts: list[str]) -> list[list[float]]:
    return Embedder().embed(texts)
