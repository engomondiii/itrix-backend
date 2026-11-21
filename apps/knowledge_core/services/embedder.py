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
attempt. If that real embedding fails, it raises and the retriever falls back to PostgreSQL
keyword retrieval instead of querying Pinecone with a meaningless pseudo-vector.
"""

from __future__ import annotations

import hashlib
import logging
import struct
import time
from collections import OrderedDict
from threading import Lock

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


# Only query vectors are cached, never retrieved documents or generated answers.
# Bounded process-local storage contains hashes and vectors, not question text.
_QUERY_VECTORS = OrderedDict()
_QUERY_VECTOR_LOCK = Lock()
_QUERY_VECTOR_TTL = 600
_QUERY_VECTOR_LIMIT = 128


class EmbeddingUnavailable(RuntimeError):
    """A real embedding was required but OpenAI did not return one."""

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
            from apps.ai_engine.services.client_pool import reusable_client
            self._client = reusable_client(
                "openai", (settings.OPENAI_API_KEY, _timeout_seconds()),
                lambda: OpenAI(
                    api_key=settings.OPENAI_API_KEY,
                    timeout=_timeout_seconds(),
                    max_retries=0,
                ),
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
            "OpenAI embedding failed after %d attempt(s); refusing pseudo-vectors while AI is enabled: %s",
            attempts, last_exc,
        )
        raise EmbeddingUnavailable(str(last_exc) or "OpenAI embedding failed") from last_exc

    def embed_one(self, text: str) -> list[float]:
        """
        Single-query embedding for the LIVE request path (RAG retrieval).

        Bounded and sleep-free: at most one attempt (plus the client's own hard timeout).
        Failure raises ``EmbeddingUnavailable`` so the retriever uses its deterministic
        keyword fallback rather than sending a pseudo-vector to Pinecone.
        """
        if not self.enabled:
            return self.embed([text], retries=0, backoff=False)[0]
        key = (
            hashlib.sha256(settings.OPENAI_API_KEY.encode()).digest(),
            settings.OPENAI_EMBEDDING_MODEL,
            hashlib.sha256(text.encode("utf-8")).digest(),
        )
        with _QUERY_VECTOR_LOCK:
            cached = _QUERY_VECTORS.get(key)
            if cached is not None and time.monotonic() < cached[0]:
                _QUERY_VECTORS.move_to_end(key)
                return list(cached[1])
            _QUERY_VECTORS.pop(key, None)
        # Network work stays outside the lock so unrelated visitors never wait.
        vector = self.embed([text], retries=0, backoff=False)[0]
        with _QUERY_VECTOR_LOCK:
            _QUERY_VECTORS[key] = (time.monotonic() + _QUERY_VECTOR_TTL, tuple(vector))
            _QUERY_VECTORS.move_to_end(key)
            while len(_QUERY_VECTORS) > _QUERY_VECTOR_LIMIT:
                _QUERY_VECTORS.popitem(last=False)
        return vector


def embed_texts(texts: list[str]) -> list[list[float]]:
    return Embedder().embed(texts)
