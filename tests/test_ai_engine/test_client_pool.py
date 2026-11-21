from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import pytest

from apps.ai_engine.services import client_pool


@pytest.fixture(autouse=True)
def clear_pool():
    from apps.ai_engine.services.pinecone_client import _shared_index
    _shared_index.cache_clear()
    client_pool._state.clients = {}
    yield
    client_pool._state.clients = {}


def test_reuse_and_rotation_close_old_transport():
    first, second = Mock(), Mock()
    factory = Mock(side_effect=[first, second])
    assert client_pool.reusable_client('test', ('key', 20), factory) is first
    assert client_pool.reusable_client('test', ('key', 20), factory) is first
    assert factory.call_count == 1
    assert client_pool.reusable_client('test', ('new-key', 20), factory) is second
    first.close.assert_called_once()


def test_threads_and_forked_workers_do_not_share_clients():
    factory = Mock(side_effect=lambda: Mock())
    first = client_pool.reusable_client('test', (), factory)
    with ThreadPoolExecutor(max_workers=1) as pool:
        other = pool.submit(client_pool.reusable_client, 'test', (), factory).result()
        again = pool.submit(client_pool.reusable_client, 'test', (), factory).result()
    assert other is again and other is not first
    with patch.object(client_pool.os, 'getpid', return_value=-1):
        assert client_pool.reusable_client('test', (), factory) is not first
    first.close.assert_not_called()


def test_failed_initialization_is_not_cached():
    factory = Mock(side_effect=[RuntimeError('unavailable'), Mock()])
    with pytest.raises(RuntimeError):
        client_pool.reusable_client('test', (), factory)
    assert client_pool.reusable_client('test', (), factory) is not None
    assert factory.call_count == 2


def test_provider_wrappers_reuse_connections_without_caching_answers(settings):
    settings.ENABLE_AI_ENGINE = True
    settings.ANTHROPIC_API_KEY = 'test-anthropic'
    settings.OPENAI_API_KEY = 'test-openai'
    settings.PINECONE_API_KEY = 'test-pinecone'
    from apps.ai_engine.services.claude_client import ClaudeClient
    from apps.ai_engine.services.pinecone_client import PineconeQueryClient
    from apps.knowledge_core.services.embedder import Embedder
    with patch('anthropic.Anthropic') as anthropic, patch('openai.OpenAI') as openai, patch('pinecone.Pinecone') as pinecone:
        assert ClaudeClient().client is ClaudeClient().client
        assert Embedder().client is Embedder().client
        assert PineconeQueryClient().index is PineconeQueryClient().index
        anthropic.assert_called_once()
        openai.assert_called_once()
        pinecone.assert_called_once()
        pinecone.return_value.Index.assert_called_once_with(settings.PINECONE_INDEX)
        # Reuse the transport only: two embedding calls still reach the provider.
        openai.return_value.embeddings.create.return_value.data = [Mock(embedding=[1.0])]
        Embedder().embed_one('question one')
        Embedder().embed_one('question two')
        assert openai.return_value.embeddings.create.call_count == 2


def test_prompt_cache_preserves_exact_context_and_changed_sources():
    from apps.ai_engine.services.claude_client import _stream_system_blocks
    system = "Shared accuracy rules\n\nINTERNAL ORCHESTRATION CONTEXT\nfresh source A"
    blocks = _stream_system_blocks(system)
    assert "".join(block["text"] for block in blocks) == system
    changed = _stream_system_blocks(system.replace("source A", "source B"))
    assert blocks[0] == changed[0]
    assert blocks[1] != changed[1]
    assert _stream_system_blocks("other agent") == "other agent"


def test_vector_query_omits_duplicate_metadata_but_preserves_access_filter(settings):
    settings.ENABLE_AI_ENGINE = True
    settings.PINECONE_API_KEY = 'test-pinecone'
    from apps.ai_engine.services.pinecone_client import PineconeQueryClient
    client = PineconeQueryClient()
    client._index = Mock()
    client._index.query.return_value = {'matches': [{'id': 'current-chunk', 'score': 0.9}]}
    access_filter = {'disclosure_level': {'$in': ['public']}}
    matches = client.query(vector=[0.1], top_k=32, namespace='astop', metadata_filter=access_filter)
    assert matches[0]['id'] == 'current-chunk'
    assert matches[0]['score'] == 0.9
    args = client._index.query.call_args.kwargs
    assert args['include_metadata'] is False
    assert args['filter'] == access_filter
    assert args['top_k'] == 32


def test_search_transport_reused_across_generation_threads(settings):
    settings.ENABLE_AI_ENGINE = True
    settings.PINECONE_API_KEY = 'thread-test'
    from apps.ai_engine.services.pinecone_client import PineconeQueryClient
    with patch('pinecone.Pinecone') as provider:
        first = PineconeQueryClient().index
        with ThreadPoolExecutor(max_workers=1) as pool:
            second = pool.submit(lambda: PineconeQueryClient().index).result()
        assert first is second
        provider.assert_called_once()
        settings.PINECONE_INDEX = 'different-index'
        PineconeQueryClient().index
        assert provider.call_count == 2
