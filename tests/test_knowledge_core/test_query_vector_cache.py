from unittest.mock import Mock

import pytest

from apps.knowledge_core.services import embedder


@pytest.fixture(autouse=True)
def cache_settings(settings):
    settings.ENABLE_AI_ENGINE = True
    settings.OPENAI_API_KEY = 'query-cache-test'
    settings.OPENAI_EMBEDDING_MODEL = 'text-embedding-3-small'
    embedder._QUERY_VECTORS.clear()
    yield
    embedder._QUERY_VECTORS.clear()


def test_exact_queries_reuse_vectors_not_mutable_results(monkeypatch):
    provider = Mock(return_value=[[0.1, 0.2]])
    monkeypatch.setattr(embedder.Embedder, '_embed_once', provider)
    first = embedder.Embedder().embed_one('ASTOP?')
    first[0] = 9
    assert embedder.Embedder().embed_one('ASTOP?') == [0.1, 0.2]
    assert provider.call_count == 1
    embedder.Embedder().embed_one('ASTOP requirements?')
    assert provider.call_count == 2


def test_expiry_model_and_credentials_invalidate(settings, monkeypatch):
    provider = Mock(side_effect=lambda _: [[0.1]])
    monkeypatch.setattr(embedder.Embedder, '_embed_once', provider)
    now = [0]
    monkeypatch.setattr(embedder.time, 'monotonic', lambda: now[0])
    embedder.Embedder().embed_one('question')
    now[0] = 601
    embedder.Embedder().embed_one('question')
    settings.OPENAI_EMBEDDING_MODEL = 'text-embedding-3-large'
    embedder.Embedder().embed_one('question')
    settings.OPENAI_API_KEY = 'rotated'
    embedder.Embedder().embed_one('question')
    assert provider.call_count == 4


def test_failures_not_cached_and_storage_bounded(monkeypatch):
    provider = Mock(side_effect=[RuntimeError('unavailable'), [[0.1]], [[0.2]], [[0.3]]])
    monkeypatch.setattr(embedder.Embedder, '_embed_once', provider)
    monkeypatch.setattr(embedder, '_QUERY_VECTOR_LIMIT', 2)
    with pytest.raises(embedder.EmbeddingUnavailable):
        embedder.Embedder().embed_one('one')
    assert not embedder._QUERY_VECTORS
    for text in ('one', 'two', 'three'):
        embedder.Embedder().embed_one(text)
    assert len(embedder._QUERY_VECTORS) == 2


def test_offline_vectors_never_enter_live_cache(settings):
    settings.ENABLE_AI_ENGINE = False
    embedder.Embedder().embed_one('question')
    assert not embedder._QUERY_VECTORS
