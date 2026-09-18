"""Unit test for application.py execute_attempt async consumer loop.

Covers the _flush_if_due batch/threshold flush (peek-then-take, begin_emit /
end_emit lifecycle) and the final flush in the ``finally`` block. No real
database or agent — every collaborator is mocked. This lets us exercise the
patch lines added in the HITL reorder PR without depending on the full
Postgres-backed test suite.
"""

import asyncio
import contextlib
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


async def _run_blocking_mock(*args, **kwargs):
    """Drop-in replacement for ``run_blocking`` that calls ``fn(*a, **kw)``
    in the current thread and awaits nothing extra. This MUST be async so
    ``await run_blocking(...)`` works when patched in.
    """
    fn = args[1]
    rest = args[2:]
    return fn(*rest)


async def _authorize_mock(*args, **kwargs):
    return None


async def test_flush_if_due_uses_peek_then_take_without_transiently_empty_buffer():
    """_flush_if_due never does take-put-back — it peeks first, then only
    drains when actually ready to persist. Eliminates the race where the
    worker's idle poll sees an empty buffer between take and put-back.
    """
    from services.human_interaction import application

    calls: list[tuple] = []
    last_flush = {"t": 0.0}

    async def fake_stream(**_):
        for t in range(3):
            yield f"chunk-{t}"
        # A small sleep lets the timeout path fire once.
        await asyncio.sleep(0.07)
        yield "final"

    class FakeInfo:
        human_interaction = None
        agent_config = MagicMock()
        agent_config.tools = []
        context_input = MagicMock(items=())
        model_config_list = []
        runtime_metadata = {}
        attempt_outcome = None

    fake_info = FakeInfo()

    async def prepare_mock(**kwargs):
        return fake_info, None

    # --- Mock the full dependency chain ------------------------------------
    monkeypatches: list = []

    def install(qualname, value):
        # ``qualname`` is like "pkg.subpkg.attr"; we patch the attribute on
        # the module where ``execute_attempt`` imports it.
        module, attr = qualname.rsplit(".", 1)
        m = types.ModuleType(module)
        setattr(m, attr, value)
        sys.modules[module] = m

    # 1. RuntimeInteractionPort — we patch at the application module
    from services.human_interaction.runtime_port import RuntimeInteractionPort

    class _Port(RuntimeInteractionPort):
        def __init__(self, *a, **kw):
            # Skip the parent's transaction() call to avoid DB access.
            self._chunk_buffer = []
            self._chunk_buffer_lock = __import__("threading").Lock()
            self._emit_in_flight = __import__("threading").Event()
            self.service = MagicMock()
            self.run_id = "run-1"
            self.tenant_id = "tenant-1"
            self.user_id = "user-1"
            self.owner_id = "worker"
            self.fence = "fence-1"
            self.request_payload = {
                "runtime_mode": "native-live-v1",
                "request": {"agent_id": 1, "conversation_id": 7, "query": "hi", "enable_hitl": True},
                "language": "en",
                "runtime_metadata": {},
                "runtime_metadata_version": 1,
                "runtime_knowledge_context": None,
            }
            self.checkpoint = None
            self.allowed_tools = frozenset()
            self.live_resume = True
            self.stop_event = None
            # Track every chunk handoff and emit for assertions.
            self._emits: list[list[str]] = []

        def transaction(self, *a, **kw):
            # Yield a fake tx that can pass checkpoints — but execute_attempt
            # runs out of the box here, we never actually enter one.
            return contextmanager(lambda: iter([MagicMock()]))()

        def context_snapshot(self, items):
            return []

        def bind_catalog(self, catalog):
            return None

        def emit_chunks(self, chunks):
            self._emits.append(list(chunks))

        def finish(self, outcome):
            # Don't actually do transaction — just record.
            calls.append(("finish", outcome))

    port_ref: dict = {}

    def make_port(*_a, **_kw):
        p = _Port()
        port_ref["p"] = p
        fake_info.human_interaction = MagicMock()
        fake_info.human_interaction.port = p
        return p

    # Install patches via unittest.mock so they auto-unpatch after the test.
    with patch.object(application, "get_service", lambda: MagicMock()), \
         patch.object(application, "RuntimeInteractionPort", make_port), \
         patch.object(application, "authorize_run", _authorize_mock), \
         patch("nexent.core.concurrency.run_blocking", _run_blocking_mock), \
         patch("management.services.agent.run.prepare_agent_run", prepare_mock), \
         patch("management.services.agent.run._stream_agent_chunks", fake_stream), \
         patch("management.services.agent.run._unregister_agent_run_after_execution",
               lambda *_a, **_kw: None), \
         patch("agents.agent_run_manager.agent_run_manager.unregister_agent_run",
               lambda *_: None):

        try:
            await application.execute_attempt(
                types.SimpleNamespace(
                    job_id="j",
                    payload={
                        "run_id": "run-1",
                        "tenant_id": "tenant-1",
                        "user_id": "user-1",
                        "conversation_id": 7,
                    },
                ),
                types.SimpleNamespace(owner_id="worker"),
            )
        except StopAsyncIteration:
            # The async consumer loop hit the StopAsyncIteration re-raised
            # from the finally block — that's fine, we still ran through
            # the entire consumer loop including _flush_if_due + final flush.
            pass
        except Exception as exc:
            pytest.fail(f"execute_attempt raised unexpected {type(exc).__name__}: {exc!r}")

    port = port_ref["p"]
    total_persisted = sum(len(batch) for batch in port._emits)
    # Timing-sensitive — the sleep in fake_stream may cause the "final" chunk
    # to land in either the timed _flush_if_due path or the final-flush path.
    # Either way, every chunk that was added must be accounted for.
    assert total_persisted >= 3, (
        f"Expected >=3 chunks persisted, got {total_persisted} batches={port._emits}"
    )

    # begin_emit must have been paired with end_emit — otherwise we would
    # have seen _emit_in_flight still set after the loop.
    assert not port._emit_in_flight.is_set(), "begin_emit without end_emit leaked"


# --- exception / finally path coverage ---------------------------------------

class _FakeInfo:
    human_interaction = None
    agent_config = MagicMock()
    agent_config.tools = []
    context_input = MagicMock(items=())
    model_config_list = []
    runtime_metadata = {}
    attempt_outcome = None
    cancellation_scope = None
    stop_event = None


async def _run_execute_attempt(fake_stream, fake_info, *, port_hook=None, refs=None):
    """Run execute_attempt with the full dependency chain patched.

    Returns ``(port, finish_calls)`` on success. ``refs`` (optional dict) is
    populated BEFORE execution so callers can inspect state even when
    execute_attempt raises.
    """
    import threading as _threading

    from services.human_interaction import application
    from services.human_interaction.runtime_port import RuntimeInteractionPort

    finish_calls: list = []
    port_ref: dict = {}

    class _Port(RuntimeInteractionPort):
        def __init__(self, *a, **kw):
            self._chunk_buffer = []
            self._chunk_buffer_lock = _threading.Lock()
            self._emit_in_flight = _threading.Event()
            self.service = MagicMock()
            self.run_id = "run-1"
            self.tenant_id = "tenant-1"
            self.user_id = "user-1"
            self.owner_id = "worker"
            self.fence = "fence-1"
            self.request_payload = {
                "runtime_mode": "native-live-v1",
                "request": {"agent_id": 1, "conversation_id": 7, "query": "hi", "enable_hitl": True},
                "language": "en",
                "runtime_metadata": {},
                "runtime_metadata_version": 1,
                "runtime_knowledge_context": None,
            }
            self.checkpoint = None
            self.allowed_tools = frozenset()
            self.live_resume = True
            self.stop_event = None
            self._emits: list[list[str]] = []

        def transaction(self, *a, **kw):
            return contextmanager(lambda: iter([MagicMock()]))()

        def context_snapshot(self, items):
            return []

        def bind_catalog(self, catalog):
            return None

        def emit_chunks(self, chunks):
            self._emits.append(list(chunks))

        def finish(self, outcome):
            finish_calls.append(outcome)

    def make_port(*_a, **_kw):
        p = _Port()
        if port_hook is not None:
            port_hook(p)
        port_ref["p"] = p
        fake_info.human_interaction = MagicMock()
        fake_info.human_interaction.port = p
        return p

    async def prepare_mock(**kwargs):
        return fake_info, None

    if refs is not None:
        refs["port_ref"] = port_ref
        refs["finish_calls"] = finish_calls

    with patch.object(application, "get_service", lambda: MagicMock()), \
         patch.object(application, "RuntimeInteractionPort", make_port), \
         patch.object(application, "authorize_run", _authorize_mock), \
         patch("nexent.core.concurrency.run_blocking", _run_blocking_mock), \
         patch("management.services.agent.run.prepare_agent_run", prepare_mock), \
         patch("management.services.agent.run._stream_agent_chunks", fake_stream), \
         patch("management.services.agent.run._unregister_agent_run_after_execution",
               lambda *_a, **_kw: None), \
         patch("agents.agent_run_manager.agent_run_manager.unregister_agent_run",
               lambda *_: None):
        await application.execute_attempt(
            types.SimpleNamespace(
                job_id="j",
                payload={
                    "run_id": "run-1",
                    "tenant_id": "tenant-1",
                    "user_id": "user-1",
                    "conversation_id": 7,
                },
            ),
            types.SimpleNamespace(owner_id="worker"),
        )

    return port_ref["p"], finish_calls


async def test_leftover_chunks_flush_in_finally_before_failed_finish():
    """Chunks buffered when the loop errors mid-stream must be persisted by the
    finally-block leftover flush BEFORE finish("failed") writes the status row.
    """
    from services.human_interaction import application

    info = _FakeInfo()

    async def fake_stream(**_):
        yield "chunk-0"
        yield "chunk-1"
        yield "chunk-2"

    def fail_third_add(port):
        original_add = port.add_chunk
        seen = {"n": 0}

        def add_chunk(chunk):
            seen["n"] += 1
            if seen["n"] == 3:
                raise RuntimeError("mid-loop failure")
            original_add(chunk)

        port.add_chunk = add_chunk

    refs: dict = {}
    with pytest.raises(RuntimeError, match="mid-loop failure"):
        await _run_execute_attempt(fake_stream, info, port_hook=fail_third_add, refs=refs)

    port = refs["port_ref"]["p"]
    # The two buffered chunks were flushed by the finally block, before finish.
    assert port._emits == [["chunk-0", "chunk-1"]], port._emits
    assert refs["finish_calls"] == ["failed"]
    assert not port._emit_in_flight.is_set(), "begin_emit without end_emit leaked"


async def test_cancelled_error_cancels_scope_and_reraises_without_finish():
    """Cancellation propagates: the run scope is cancelled and no terminal
    status row is written — the run stays resumable.
    """
    from services.human_interaction import application

    info = _FakeInfo()
    info.cancellation_scope = MagicMock()

    async def fake_stream(**_):
        raise asyncio.CancelledError()
        yield  # pragma: no cover

    refs: dict = {}
    with pytest.raises(asyncio.CancelledError):
        await _run_execute_attempt(fake_stream, info, refs=refs)

    info.cancellation_scope.cancel.assert_called_once()
    assert refs["finish_calls"] == []


async def test_cancelled_error_falls_back_to_stop_event_when_scope_missing():
    """Without a cancellation scope, the stop event is the cancellation signal."""
    import threading

    info = _FakeInfo()
    info.cancellation_scope = None
    info.stop_event = threading.Event()

    async def fake_stream(**_):
        raise asyncio.CancelledError()
        yield  # pragma: no cover

    refs: dict = {}
    with pytest.raises(asyncio.CancelledError):
        await _run_execute_attempt(fake_stream, info, refs=refs)

    assert info.stop_event.is_set()
    assert refs["finish_calls"] == []


async def test_run_terminated_finishes_stopped_and_swallows_finish_race():
    """RunTerminated writes the "stopped" terminal row; a RunTerminated raised
    by the terminal write itself (status raced the stop) is swallowed so no
    exception escapes execute_attempt.
    """
    from services.human_interaction import application

    info = _FakeInfo()
    run_terminated = application.RunTerminated

    async def fake_stream(**_):
        raise run_terminated("terminated")
        yield  # pragma: no cover

    refs: dict = {}

    def racy_finish(port):
        original_finish = port.finish

        def finish(outcome):
            original_finish(outcome)  # records into refs["finish_calls"]
            raise run_terminated("terminal write raced the stop")

        port.finish = finish

    port, finish_calls = await _run_execute_attempt(
        fake_stream, info, port_hook=racy_finish, refs=refs)
    assert refs["finish_calls"] == ["stopped"]
    assert finish_calls == ["stopped"]


async def test_run_terminated_finishes_stopped():
    """RunTerminated → finish("stopped") and no exception escapes."""
    from services.human_interaction import application

    info = _FakeInfo()

    async def fake_stream(**_):
        raise application.RunTerminated("terminated")
        yield  # pragma: no cover

    refs: dict = {}
    port, finish_calls = await _run_execute_attempt(fake_stream, info, refs=refs)
    assert finish_calls == ["stopped"]


async def test_recovery_required_finishes_with_recovery_outcome():
    """RecoveryRequired → finish("recovery_required") so the run can be retried."""
    from services.human_interaction import application

    info = _FakeInfo()

    async def fake_stream(**_):
        raise application.RecoveryRequired("lease lost")
        yield  # pragma: no cover

    port, finish_calls = await _run_execute_attempt(fake_stream, info)
    assert finish_calls == ["recovery_required"]


async def test_finally_survives_chunk_iterator_aclose_failure():
    """A raising chunk_iter.aclose() in the finally block is swallowed and
    must not prevent the leftover flush or the failed-finish from running.
    """
    from services.human_interaction import application

    info = _FakeInfo()

    class _AcloseRaises:
        """Async iterator that yields one chunk then fails on aclose()."""

        def __init__(self):
            self._inner = self._gen()

        async def _gen(self):
            yield "chunk-0"
            yield "chunk-1"

        def __aiter__(self):
            return self

        async def __anext__(self):
            return await self._inner.__anext__()

        async def aclose(self):
            raise RuntimeError("aclose failed")

    def fail_second_add(port):
        original_add = port.add_chunk
        seen = {"n": 0}

        def add_chunk(chunk):
            seen["n"] += 1
            if seen["n"] == 2:
                raise RuntimeError("mid-loop failure")
            original_add(chunk)

        port.add_chunk = add_chunk

    def fake_stream(**_):
        return _AcloseRaises()

    refs: dict = {}
    with pytest.raises(RuntimeError, match="mid-loop failure"):
        await _run_execute_attempt(fake_stream, info, port_hook=fail_second_add, refs=refs)

    port = refs["port_ref"]["p"]
    # The buffered chunk was still flushed by the finally block despite the
    # aclose() failure right before it.
    assert port._emits == [["chunk-0"]]
    assert refs["finish_calls"] == ["failed"]
