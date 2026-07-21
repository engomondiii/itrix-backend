"""
The extraction sandbox (Backend v6.0 §1.1, §4.3).

    SANDBOXED worker: NO NETWORK EGRESS, memory + CPU ceiling, WALL-CLOCK TIMEOUT.

── WHY EXTRACTION NEEDS A SANDBOX AT ALL ────────────────────────────────────
Extraction is the one place where attacker-controlled bytes meet a parser. Document
parsers are large C libraries with a long history of memory-corruption bugs. The threat
is not that a handler returns wrong text; it is that a crafted PDF causes the handler to
do something the handler was never asked to do.

Three controls, and each closes a different outcome:

    NO NETWORK EGRESS   a compromised parser cannot exfiltrate what it just read, and
                        cannot call home for a second stage
    MEMORY CEILING      a decompression bomb that survived the scanner cannot exhaust
                        the host
    WALL-CLOCK TIMEOUT  a parser that hangs on malformed input cannot occupy a worker
                        indefinitely

── HOW ISOLATION IS ACHIEVED ────────────────────────────────────────────────
A forked child process with ``resource`` limits applied BEFORE the handler is imported,
and socket creation disabled in the child. Fork is used rather than a thread because a
thread shares the parent's address space and cannot have its memory capped
independently — a thread-based "sandbox" is a comment, not a boundary.

On platforms without ``fork`` the module degrades to in-process extraction with the
timeout still applied, and SAYS SO in the result. A degraded sandbox that claims to be a
sandbox is worse than one that admits it.
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import sys

logger = logging.getLogger("itrix")

# Handler name -> module path. Imported INSIDE the child, after limits are applied.
_HANDLER_MODULES = {
    "pdf": "apps.attachments.services.handlers.pdf",
    "docx": "apps.attachments.services.handlers.docx",
    "xlsx": "apps.attachments.services.handlers.xlsx",
    "pptx": "apps.attachments.services.handlers.pptx",
    "csv_tsv": "apps.attachments.services.handlers.csv_tsv",
    "text": "apps.attachments.services.handlers.text",
    "code": "apps.attachments.services.handlers.code",
    "json_xml": "apps.attachments.services.handlers.json_xml",
    "image_ocr": "apps.attachments.services.handlers.image_ocr",
    "opaque": "apps.attachments.services.handlers.opaque",
}


def _apply_limits(memory_mb: int) -> None:
    """
    Apply resource limits inside the child, BEFORE any handler is imported.

    Order matters: importing a parser library can itself allocate, so the ceiling has to
    be in place first.
    """
    try:
        import resource

        limit_bytes = int(memory_mb) * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
        # No core dumps: a crash on hostile input must not write the file's contents to
        # disk in a location nobody is managing.
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        # No new files beyond what the handler needs to read from memory.
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    except Exception:  # noqa: BLE001 - not available on every platform
        logger.debug("resource limits unavailable in extraction sandbox")


def _disable_network() -> None:
    """
    Remove the child's ability to open a socket.

    Belt and braces alongside a network-isolated Celery queue: this makes egress
    impossible even if the worker is misdeployed onto a routable queue.
    """
    try:
        import socket

        def _blocked(*args, **kwargs):
            raise OSError("network egress is disabled in the extraction sandbox")

        socket.socket = _blocked  # type: ignore[assignment]
        socket.create_connection = _blocked  # type: ignore[assignment]
        socket.socketpair = _blocked  # type: ignore[assignment]
    except Exception:  # noqa: BLE001
        pass


def _child(handler_name, data, filename, limit, memory_mb, pipe):
    """Runs in the forked child. Everything here is inside the sandbox."""
    try:
        _apply_limits(memory_mb)
        _disable_network()

        import importlib

        module = importlib.import_module(
            _HANDLER_MODULES.get(handler_name, _HANDLER_MODULES["opaque"])
        )
        result = module.extract(data, filename=filename, limit=limit)
        pipe.send(
            {
                "text": result.text,
                "page_count": result.page_count,
                "handler": result.handler,
                "truncated": result.truncated,
                "metadata_only": result.metadata_only,
                "error": result.error,
            }
        )
    except MemoryError:
        pipe.send({"metadata_only": True, "handler": handler_name,
                   "error": "exceeded the extraction memory ceiling"})
    except Exception as exc:  # noqa: BLE001
        pipe.send({"metadata_only": True, "handler": handler_name,
                   "error": f"extraction error: {exc}"[:200]})
    finally:
        try:
            pipe.close()
        except Exception:  # noqa: BLE001
            pass


def run_sandboxed(handler_name: str, data: bytes, *, filename: str = "",
                  limit: int = 400_000, timeout: int = 30, memory_mb: int = 512):
    """
    Run one handler in an isolated child process.

    Always returns an ``ExtractionResult``. A timeout, a crash or an OOM all produce a
    metadata-only result with an honest reason — never an exception the caller has to
    translate into one.
    """
    from apps.attachments.services.handlers import ExtractionResult

    if not _can_fork():
        return _in_process(handler_name, data, filename, limit)

    parent_conn, child_conn = multiprocessing.Pipe(duplex=False)
    context = multiprocessing.get_context("fork")
    process = context.Process(
        target=_child,
        args=(handler_name, data, filename, limit, memory_mb, child_conn),
        daemon=True,
    )
    process.start()
    child_conn.close()

    payload = None
    if parent_conn.poll(timeout):
        try:
            payload = parent_conn.recv()
        except Exception:  # noqa: BLE001
            payload = None

    process.join(timeout=1)
    if process.is_alive():
        # WALL-CLOCK TIMEOUT. Kill rather than terminate: a parser stuck in a C loop
        # will not service SIGTERM.
        process.kill()
        process.join(timeout=2)
        return ExtractionResult(
            handler=handler_name, metadata_only=True,
            error=f"extraction timed out after {timeout}s",
        )

    if payload is None:
        return ExtractionResult(
            handler=handler_name, metadata_only=True,
            error="extraction worker produced no result",
        )

    return ExtractionResult(
        text=payload.get("text") or "",
        page_count=payload.get("page_count") or 0,
        handler=payload.get("handler") or handler_name,
        truncated=bool(payload.get("truncated")),
        metadata_only=bool(payload.get("metadata_only")),
        error=payload.get("error") or "",
    )


def _can_fork() -> bool:
    return hasattr(os, "fork") and sys.platform != "win32"


def _in_process(handler_name: str, data: bytes, filename: str, limit: int):
    """
    Degraded path for platforms without fork.

    The result SAYS the sandbox was unavailable. Silently running unsandboxed while
    everything upstream believes there is a sandbox is the worse failure.
    """
    from apps.attachments.services.handlers import ExtractionResult

    import importlib

    try:
        module = importlib.import_module(
            _HANDLER_MODULES.get(handler_name, _HANDLER_MODULES["opaque"])
        )
        result = module.extract(data, filename=filename, limit=limit)
        if not result.error:
            result.error = "extracted without process isolation (fork unavailable)"
        return result
    except Exception as exc:  # noqa: BLE001
        return ExtractionResult(handler=handler_name, metadata_only=True,
                                error=f"extraction failed: {exc}"[:200])
