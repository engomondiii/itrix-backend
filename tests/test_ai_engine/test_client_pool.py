from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import pytest

from apps.ai_engine.services import client_pool


@pytest.fixture(autouse=True)
def clear_pool():
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
