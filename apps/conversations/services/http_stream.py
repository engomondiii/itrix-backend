"""Incremental HTTP delivery for the existing, session-authorized turn endpoints."""
import asyncio
import json
import logging
from threading import Event

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import close_old_connections
from django.http import StreamingHttpResponse

logger = logging.getLogger('itrix')
_running = set()


def requested(request):
    return request.headers.get('X-Itrix-Stream') == '1' and getattr(settings, 'ENABLE_ANONYMOUS_STREAMING', False)


def response(thread, visitor, body, request_id):
    from apps.conversations.serializers_thread import ThreadTurnSerializer
    initial = {'threadId': str(thread.id), 'title': thread.title, 'turn': dict(ThreadTurnSerializer(visitor).data),
               'assistantTurn': None, 'generationStatus': 'pending'}
    message_id = 'stream_' + str(visitor.id)

    async def events():
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()
        disconnected = Event()

        def emit(event):
            if not disconnected.is_set():
                loop.call_soon_threadsafe(queue.put_nowait, event)

        def generate():
            from apps.conversations.views_thread import _attempt_assistant_generation
            close_old_connections()
            try:
                attempt = _attempt_assistant_generation(
                    thread, body, request_id=request_id,
                    on_delta=lambda text: emit({'type': 'delta', 'messageId': message_id, 'delta': text}),
                )
                emit({'type': 'final', 'data': {**initial, 'assistantTurn': attempt.turn,
                                               'generationStatus': attempt.state}})
            except Exception:
                logger.exception('HTTP chat stream failed request_id=%s', request_id)
                emit({'type': 'final', 'data': {**initial, 'generationStatus': 'failed'}})
            finally:
                close_old_connections()

        def encode(event):
            return (json.dumps(event, cls=DjangoJSONEncoder, ensure_ascii=False) + '\n').encode()

        # Deliver the persisted visitor turn and session cookie before model latency.
        yield encode({'type': 'accepted', 'data': initial, 'messageId': message_id})
        task = asyncio.create_task(asyncio.to_thread(generate))
        _running.add(task)
        task.add_done_callback(_running.discard)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=5)
                except asyncio.TimeoutError:
                    yield encode({'type': 'ping'})
                    continue
                yield encode(event)
                if event['type'] == 'final':
                    break
        finally:
            # A disconnected reader must not lose a saved turn or create a second
            # generation. The bounded provider call finishes and persists normally.
            disconnected.set()

    out = StreamingHttpResponse(events(), status=201, content_type='application/x-ndjson')
    out['Cache-Control'] = 'no-store, no-transform'
    out['X-Accel-Buffering'] = 'no'
    return out
