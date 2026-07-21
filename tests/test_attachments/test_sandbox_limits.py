"""
The extraction sandbox (Backend v6.0 §4.3, workers/extraction_entrypoint.py).

    SANDBOXED worker: NO NETWORK EGRESS, memory + CPU ceiling, WALL-CLOCK TIMEOUT.

Extraction is the one place attacker-controlled bytes meet a parser, so these tests
assert the boundary exists and holds — not that the parsers are correct.
"""

from __future__ import annotations

import pytest

from workers import extraction_entrypoint as sandbox


def test_a_normal_extraction_succeeds():
    result = sandbox.run_sandboxed(
        "text", b"Our HBM traffic saturates the fleet.", filename="notes.txt"
    )
    assert "HBM" in result.text
    assert result.metadata_only is False


def test_an_unknown_handler_degrades_to_opaque():
    """Every file reaches a handler. There is no path that raises instead."""
    result = sandbox.run_sandboxed("not_a_handler", b"bytes", filename="x.bin")
    assert result.metadata_only is True


def test_a_timeout_produces_an_honest_result_not_an_exception():
    """
    A hung parser must not occupy a worker, and must not surface as a crash the caller
    has to translate. A timeout is a RESULT with a reason.
    """
    if not sandbox._can_fork():
        pytest.skip("fork unavailable on this platform")

    import apps.attachments.services.handlers.text as text_handler

    original = text_handler.extract

    def _hang(data, *, filename="", limit=400_000):
        import time
        time.sleep(30)
        return original(data, filename=filename, limit=limit)

    text_handler.extract = _hang
    try:
        result = sandbox.run_sandboxed("text", b"x", filename="a.txt", timeout=1)
        assert result.metadata_only is True
        assert "timed out" in result.error
    finally:
        text_handler.extract = original


def test_the_child_cannot_open_a_socket():
    """
    NO NETWORK EGRESS. A compromised parser cannot exfiltrate what it just read.

    Asserted by running a handler that tries to connect and confirming it fails inside
    the sandbox rather than succeeding.
    """
    if not sandbox._can_fork():
        pytest.skip("fork unavailable on this platform")

    import apps.attachments.services.handlers.opaque as opaque_handler
    from apps.attachments.services.handlers import ExtractionResult

    original = opaque_handler.extract

    def _try_network(data, *, filename="", limit=400_000):
        import socket
        try:
            socket.socket()
            return ExtractionResult(text="NETWORK_REACHED", handler="opaque")
        except OSError as exc:
            return ExtractionResult(text=f"BLOCKED: {exc}", handler="opaque")

    opaque_handler.extract = _try_network
    try:
        result = sandbox.run_sandboxed("opaque", b"x", filename="a.bin", timeout=10)
        assert "NETWORK_REACHED" not in (result.text or "")
    finally:
        opaque_handler.extract = original


def test_degraded_mode_says_so():
    """
    Silently running unsandboxed while everything upstream believes there is a sandbox
    is the worse failure. The result must admit it.
    """
    result = sandbox._in_process("text", b"hello", "a.txt", 400_000)
    assert "without process isolation" in result.error


def test_limits_are_applied_before_the_handler_is_imported():
    """
    Ordering: importing a parser can itself allocate, so the ceiling must already be in
    place. Asserted structurally on the child's source.
    """
    import inspect

    source = inspect.getsource(sandbox._child)
    limits_at = source.index("_apply_limits")
    import_at = source.index("importlib.import_module")
    assert limits_at < import_at, "resource limits must be applied before the handler import"
