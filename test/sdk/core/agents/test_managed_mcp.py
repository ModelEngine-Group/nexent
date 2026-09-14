import asyncio
import threading
from concurrent.futures import CancelledError
from concurrent.futures import TimeoutError as FutureTimeoutError
from unittest.mock import MagicMock

import mcp.types
import mcpadapt.core
import pytest
from nexent.core.agents.managed_mcp import ManagedMCPToolCollection
from nexent.core.concurrency import LanePolicy, RunCancellationScope, ThreadManager


class _BlockingAsyncSession:
    def __init__(self, entered: threading.Event, cancelled: threading.Event):
        self.entered = entered
        self.cancelled = cancelled

    async def call_tool(self, name, arguments):
        self.entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled.set()


class _AsyncMCPContext:
    def __init__(self, session, exited: threading.Event):
        self.session = session
        self.exited = exited
        self.exit_count = 0

    async def __aenter__(self):
        tool = mcp.types.Tool(
            name="blocking_tool",
            description="Blocks until the session is closed",
            inputSchema={"type": "object", "properties": {}},
        )
        return self.session, [tool]

    async def __aexit__(self, exc_type, exc_value, traceback):
        self.exit_count += 1
        self.exited.set()


def _async_context_factory(context):
    def factory(_server_parameters, **_kwargs):
        return context

    return factory


def _capture_cancelled(result, forward):
    with pytest.raises(CancelledError) as exc_info:
        forward()
    result["error"] = exc_info.value


def _manager():
    manager = ThreadManager(
        "managed-mcp-test",
        {
            "mcp-session": LanePolicy("mcp-session", 1, 0),
            "model-tool-io": LanePolicy("model-tool-io", 1, 1),
        },
    )
    manager.start()
    return manager


def test_ut_sdk_tlm_029_tool_deadline_closes_session_owner(caplog):
    manager = _manager()
    scope = RunCancellationScope()
    entered = threading.Event()
    cancelled = threading.Event()
    exited = threading.Event()
    context = _AsyncMCPContext(_BlockingAsyncSession(entered, cancelled), exited)

    with (
        ManagedMCPToolCollection(
            manager=manager,
            server_parameters=[{"url": "http://mcp.invalid/mcp"}],
            cancellation_scope=scope,
            tool_timeout_seconds=0.02,
            close_timeout_seconds=0.5,
            session_context_factory=_async_context_factory(context),
        ) as collection,
        pytest.raises(FutureTimeoutError),
    ):
        collection.tools[0].forward(value="secret-tool-argument")

    assert entered.is_set()
    assert cancelled.wait(1)
    assert exited.wait(1)
    assert context.exit_count == 1
    assert manager.snapshot().active_count == 0
    timeout_records = [
        record
        for record in caplog.records
        if "event=mcp_tool_timeout" in record.getMessage()
    ]
    assert len(timeout_records) == 1
    assert timeout_records[0].levelname == "WARNING"
    assert "tool_name=blocking_tool" in timeout_records[0].getMessage()
    assert "timeout_seconds=0.020" in timeout_records[0].getMessage()
    assert "secret-tool-argument" not in caplog.text
    asyncio.run(manager.shutdown(timeout=1))


def test_ut_sdk_tlm_029_run_cancel_closes_blocked_mcp_tool():
    manager = _manager()
    scope = RunCancellationScope()
    entered = threading.Event()
    cancelled = threading.Event()
    exited = threading.Event()
    context = _AsyncMCPContext(_BlockingAsyncSession(entered, cancelled), exited)
    result = {}

    with ManagedMCPToolCollection(
        manager=manager,
        server_parameters=[{"url": "http://mcp.invalid/mcp"}],
        cancellation_scope=scope,
        tool_timeout_seconds=1,
        close_timeout_seconds=0.5,
        session_context_factory=_async_context_factory(context),
    ) as collection:
        caller = threading.Thread(
            target=_capture_cancelled,
            args=(result, collection.tools[0].forward),
        )
        caller.start()
        assert entered.wait(1)
        scope.cancel()
        caller.join(1)

    assert caller.is_alive() is False
    assert exited.is_set()
    assert context.exit_count == 1
    assert cancelled.is_set()
    assert isinstance(result["error"], CancelledError)
    assert manager.snapshot().active_count == 0
    asyncio.run(manager.shutdown(timeout=1))


def test_ut_sdk_tlm_032_tool_deadline_cancels_active_call_future(monkeypatch):
    manager = _manager()
    scope = RunCancellationScope()
    entered = threading.Event()
    cancelled = threading.Event()
    exited = threading.Event()
    context = _AsyncMCPContext(_BlockingAsyncSession(entered, cancelled), exited)
    session_factory = MagicMock(return_value=context)
    sync_mcpadapt = MagicMock(side_effect=AssertionError("sync MCPAdapt must not run"))
    monkeypatch.setattr(mcpadapt.core, "MCPAdapt", sync_mcpadapt)

    with (
        ManagedMCPToolCollection(
            manager=manager,
            server_parameters=[{"url": "http://mcp.invalid/mcp"}],
            cancellation_scope=scope,
            tool_timeout_seconds=0.02,
            close_timeout_seconds=0.5,
            session_context_factory=session_factory,
        ) as collection,
        pytest.raises(FutureTimeoutError),
    ):
        collection.tools[0].forward()

    assert entered.is_set()
    assert cancelled.wait(1)
    assert exited.wait(1)
    assert context.exit_count == 1
    assert session_factory.call_args.kwargs["client_session_timeout_seconds"] is None
    sync_mcpadapt.assert_not_called()
    assert manager.snapshot().active_count == 0
    asyncio.run(manager.shutdown(timeout=1))


def test_ut_sdk_tlm_032_run_cancel_cancels_active_call_future():
    manager = _manager()
    scope = RunCancellationScope()
    entered = threading.Event()
    cancelled = threading.Event()
    exited = threading.Event()
    context = _AsyncMCPContext(_BlockingAsyncSession(entered, cancelled), exited)
    result = {}

    with ManagedMCPToolCollection(
        manager=manager,
        server_parameters=[{"url": "http://mcp.invalid/mcp"}],
        cancellation_scope=scope,
        tool_timeout_seconds=1,
        close_timeout_seconds=0.5,
        session_context_factory=_async_context_factory(context),
    ) as collection:
        caller = threading.Thread(
            target=_capture_cancelled,
            args=(result, collection.tools[0].forward),
        )
        caller.start()
        assert entered.wait(1)
        scope.cancel()
        caller.join(1)

    assert caller.is_alive() is False
    assert "error" in result
    assert cancelled.is_set()
    assert exited.is_set()
    assert context.exit_count == 1
    assert manager.snapshot().active_count == 0
    asyncio.run(manager.shutdown(timeout=1))
