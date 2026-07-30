"""
``message.stage`` — the pending indicator's honest half (Backend v7.1 Phase 2, §14.3).

── WHAT THESE TESTS ARE PROTECTING ─────────────────────────────────────────

Not a feature. A promise. The surface shows a visitor one of three sentences while itriX
works, and they advance ONLY when the pipeline actually changes stage — no timer, no
interpolation, no optimistic progression.

A progress display that advances on its own looks better for one turn and costs the
visitor's trust in every other statement the surface makes. This platform's whole
proposition is that what it tells you is governed and true; a faked progress bar
establishes that it will say convenient things.

These are plain async tests with a list-collecting fake transport — no channel layer and no
``pytest-asyncio`` needed, so they run in any environment.
"""

from __future__ import annotations

import asyncio

from apps.realtime.services import stage_events


class _Collector:
    """A fake transport. Records what would have gone to the socket."""

    def __init__(self, fail: bool = False):
        self.sent: list[dict] = []
        self._fail = fail

    async def __call__(self, message: dict):
        if self._fail:
            raise RuntimeError("socket gone")
        self.sent.append(message)


def _run(coro):
    return asyncio.run(coro)


def test_there_are_exactly_three_stages():
    """
    Adding a fourth, softening one, or making one sound busier than it is requires Governance
    sign-off — the strings are a claim about what the system is doing.
    """
    assert stage_events.STAGES == ("retrieving", "composing", "checking")


def test_the_payload_carries_the_enum_and_nothing_else_of_substance():
    """
    No percentage, no elapsed time, no estimate, no agent key. A visitor-facing progress event
    carrying an internal agent name would be a §10.5 leak wearing a progress bar.
    """
    payload = stage_events.payload(thread_id="t1", message_id="m1", stage="composing")
    assert payload == {"threadId": "t1", "messageId": "m1", "stage": "composing"}
    for forbidden in ("percent", "progress", "eta", "elapsed", "agentKey", "agent_key"):
        assert forbidden not in payload


def test_each_stage_is_emitted_at_most_once():
    """
    The pipeline calls into retrieval more than once for some agents. A naive emitter would
    send ``retrieving`` twice, which reads on screen as the indicator going backwards — i.e.
    as a fault.
    """
    collector = _Collector()
    emitter = stage_events.StageEmitter(collector, thread_id="t", message_id="m")

    async def scenario():
        assert await emitter.emit("retrieving") is True
        assert await emitter.emit("retrieving") is False
        assert await emitter.emit("composing") is True

    _run(scenario())
    assert [m["payload"]["stage"] for m in collector.sent] == ["retrieving", "composing"]


def test_a_backward_stage_is_dropped():
    """
    An agent that re-queries retrieval mid-generation must not make the indicator look like it
    has lost its place. Dropping is right: the client holds its current label, which is the
    documented behaviour when no stage arrives.
    """
    collector = _Collector()
    emitter = stage_events.StageEmitter(collector, thread_id="t", message_id="m")

    async def scenario():
        await emitter.emit("composing")
        assert await emitter.emit("retrieving") is False

    _run(scenario())
    assert [m["payload"]["stage"] for m in collector.sent] == ["composing"]


def test_an_unknown_stage_is_dropped_not_forwarded():
    """The client would have no string for it and would fall back to a neutral label — which looks like a stall."""
    collector = _Collector()
    emitter = stage_events.StageEmitter(collector, thread_id="t", message_id="m")

    async def scenario():
        assert await emitter.emit("finalising") is False
        assert await emitter.emit("") is False
        assert await emitter.emit(None) is False  # type: ignore[arg-type]

    _run(scenario())
    assert collector.sent == []


def test_a_transport_failure_never_raises():
    """
    A telemetry failure must not affect delivery. The visitor's answer matters more than the
    label above it.
    """
    collector = _Collector(fail=True)
    emitter = stage_events.StageEmitter(collector, thread_id="t", message_id="m")

    async def scenario():
        assert await emitter.emit("retrieving") is False

    _run(scenario())


def test_the_full_ordered_sequence_is_permitted():
    collector = _Collector()
    emitter = stage_events.StageEmitter(collector, thread_id="t", message_id="m")

    async def scenario():
        for stage in stage_events.STAGES:
            assert await emitter.emit(stage) is True

    _run(scenario())
    assert [m["payload"]["stage"] for m in collector.sent] == list(stage_events.STAGES)
    assert emitter.sent == frozenset(stage_events.STAGES)


def test_the_consumer_emits_all_three_around_the_pipeline():
    """
    A structural check on the consumer rather than a socket test: the three emit calls sit in
    the right places relative to context-building, generation and settle.

    Asserted by reading the source because a real socket test needs a channel layer, and the
    property worth pinning is the ORDERING of the calls — which is a source fact.
    """
    import inspect

    from apps.realtime.consumers import thread as thread_consumer

    src = inspect.getsource(thread_consumer.ThreadConsumer._stream_assistant_turn)

    retrieving = src.index("STAGE_RETRIEVING")
    composing = src.index("STAGE_COMPOSING")
    checking = src.index("STAGE_CHECKING")
    build_ctx = src.index("_build_agent_context")
    settle = src.index("_settle")

    # retrieving BEFORE the context is built, because building it IS the retrieval.
    assert retrieving < build_ctx
    # composing after that and before the token loop consumes the generator.
    assert build_ctx < composing
    # checking immediately before settle.
    assert composing < checking < settle


def test_the_consumer_validates_a_stage_arriving_from_the_channel_layer():
    """
    A channel-layer message can arrive from any process in the deployment. An unknown stage
    would leave the client with a label it has no string for, so the handler re-validates
    rather than trusting the sender.
    """
    import inspect

    from apps.realtime.consumers import thread as thread_consumer

    src = inspect.getsource(thread_consumer.ThreadConsumer.message_stage)
    assert "is_stage" in src
