"""HTTP streaming must deliver before completion and retain existing ownership gates."""
import asyncio
import json
from threading import Event
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient
from apps.conversations.views_thread import GenerationAttempt

pytestmark = pytest.mark.django_db(transaction=True)


def test_first_turn_streams_before_generation_finishes(settings):
    settings.ENABLE_ANONYMOUS_STREAMING = True
    release = Event()

    def generate(*args, on_delta, **kwargs):
        on_delta('Hello ')
        assert release.wait(3), 'client must receive the delta before final completion'
        on_delta('world')
        return GenerationAttempt('failed')

    api = APIClient()
    with patch('apps.conversations.views_thread._attempt_assistant_generation', side_effect=generate):
        response = api.post('/api/v1/threads/', {'body': 'What is ASTOP?'}, format='json', HTTP_X_ITRIX_STREAM='1')
        assert response.status_code == 201
        assert response.is_async
        assert 'itrix_visitor_session' in response.cookies
        assert response['X-Accel-Buffering'] == 'no'

        async def consume():
            frames = response.streaming_content.__aiter__()
            accepted = json.loads(await anext(frames))
            assert accepted['type'] == 'accepted'
            delta = json.loads(await asyncio.wait_for(anext(frames), 2))
            assert delta['delta'] == 'Hello '
            release.set()
            assert json.loads(await anext(frames))['delta'] == 'world'
            assert json.loads(await anext(frames))['data']['generationStatus'] == 'failed'
            await frames.aclose()
            return accepted['data']['threadId']

        thread_id = asyncio.run(consume())
    denied = APIClient().post(f'/api/v1/threads/{thread_id}/turns/', {'body': 'private'}, format='json', HTTP_X_ITRIX_STREAM='1')
    assert denied.status_code in (403, 404)


def test_streaming_disabled_keeps_json_contract(settings):
    settings.ENABLE_ANONYMOUS_STREAMING = False
    with patch('apps.conversations.views_thread._attempt_assistant_generation', return_value=GenerationAttempt('failed')):
        response = APIClient().post('/api/v1/threads/', {'body': 'What is ASTOP?'}, format='json', HTTP_X_ITRIX_STREAM='1')
    assert not response.streaming
    assert response.json()['generationStatus'] == 'failed'


def test_real_generation_path_settles_streamed_reply(settings):
    settings.ENABLE_ANONYMOUS_STREAMING = True
    api = APIClient()
    with patch('apps.agents.services.concierge.ConciergeAgent.stream_reply', return_value=iter(['ASTOP ', 'reduces unnecessary AI calls.'])):
        response = api.post('/api/v1/threads/', {'body': 'What is ASTOP?'}, format='json', HTTP_X_ITRIX_STREAM='1')
        async def consume():
            return [json.loads(frame) async for frame in response.streaming_content]
        frames = asyncio.run(consume())
    assert any(f.get('delta') == 'ASTOP ' for f in frames)
    assert frames[-1]['data']['generationStatus'] == 'ready'
    assert frames[-1]['data']['assistantTurn'] is not None


def test_interrupted_provider_does_not_persist_partial_reply(settings):
    settings.ENABLE_ANONYMOUS_STREAMING = True
    def broken(self, ctx):
        yield 'Partial '
        self.stream_failed = True
    with patch('apps.agents.services.concierge.ConciergeAgent.stream_reply', broken):
        response = APIClient().post('/api/v1/threads/', {'body': 'What is ASTOP?'}, format='json', HTTP_X_ITRIX_STREAM='1')
        async def consume():
            return [json.loads(frame) async for frame in response.streaming_content]
        frames = asyncio.run(consume())
    assert frames[-1]['data']['generationStatus'] == 'failed'
    assert frames[-1]['data']['assistantTurn'] is None
