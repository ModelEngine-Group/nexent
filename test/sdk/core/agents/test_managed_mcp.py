# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import asyncio
import threading
import time
import types
from concurrent.futures import CancelledError
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import AsyncExitStack
from unittest.mock import MagicMock

import mcp.types
import mcpadapt.core
import pytest
from nexent.core.agents.contracts.config import ToolConfig
from nexent.core.agents.resources.mcp import ManagedMCPToolCollection
from nexent.consts.mcp_errors import (
    MCPConnectionFailure,
    MCPConnectionTimeoutError,
    MCPToolNotFoundError,
    MCPToolTimeoutError,
)
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
    counter = {"calls": 0}

    def factory(_server_parameters, **_kwargs):
        counter["calls"] += 1
        return context

    factory.calls = counter
    return factory


def _capture_cancelled(result, forward):
    with pytest.raises(CancelledError) as exc_info:
        forward()
    result["error"] = exc_info.value


def _fake_builder(tool_config, call_fn):
    tool = types.SimpleNamespace(name=tool_config.class_name)

    def forward(*args, **kwargs):
        # Mirror the smolagents single-positional-dict call convention.
        if len(args) == 1 and not kwargs:
            return call_fn(args[0])
        return call_fn(kwargs or None)

    tool.forward = forward
    return tool


def _tool_config(**overrides):
    values = dict(
        class_name="blocking_tool", name="blocking_tool", source="mcp",
        inputs="{}", origin_name="blocking_tool",
    )
    values.update(overrides)
    return ToolConfig(**values)


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


def _blocking_collection(manager, scope, context, **overrides):
    values = dict(
        manager=manager,
        server_parameters=[{"url": "http://mcp.invalid/mcp"}],
        cancellation_scope=scope,
        tool_timeout_seconds=0.02,
        close_timeout_seconds=0.5,
        session_context_factory=_async_context_factory(context),
        tool_builder=_fake_builder,
    )
    values.update(overrides)
    return ManagedMCPToolCollection(**values)


def test_ut_sdk_tlm_029_tool_deadline_closes_session_owner(caplog):
    manager = _manager()
    scope = RunCancellationScope()
    entered = threading.Event()
    cancelled = threading.Event()
    exited = threading.Event()
    context = _AsyncMCPContext(_BlockingAsyncSession(entered, cancelled), exited)

    with (
        _blocking_collection(manager, scope, context) as collection,
        pytest.raises(FutureTimeoutError),
    ):
        tool = collection.create_tool(_tool_config())
        tool.forward(value="secret-tool-argument")

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

    with _blocking_collection(
        manager, scope, context, tool_timeout_seconds=1,
    ) as collection:
        tool = collection.create_tool(_tool_config())
        caller = threading.Thread(
            target=_capture_cancelled,
            args=(result, tool.forward),
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
        _blocking_collection(
            manager, scope, context,
            tool_timeout_seconds=0.02, request_timeout_seconds=10,
            session_context_factory=session_factory,
        ) as collection,
        pytest.raises(FutureTimeoutError),
    ):
        tool = collection.create_tool(_tool_config())
        tool.forward()

    assert entered.is_set()
    assert cancelled.wait(1)
    assert exited.wait(1)
    assert context.exit_count == 1
    assert session_factory.call_args.kwargs["client_session_timeout_seconds"] is None
    sync_mcpadapt.assert_not_called()
    assert manager.snapshot().active_count == 0
    asyncio.run(manager.shutdown(timeout=1))


def test_ut_sdk_mcp_tool_deadline_raises_mcp_timeout_error():
    manager = _manager()
    scope = RunCancellationScope()
    entered = threading.Event()
    cancelled = threading.Event()
    exited = threading.Event()
    context = _AsyncMCPContext(_BlockingAsyncSession(entered, cancelled), exited)

    with (
        _blocking_collection(
            manager, scope, context, request_timeout_seconds=10,
        ) as collection,
        pytest.raises(MCPToolTimeoutError, match="0.02 seconds"),
    ):
        tool = collection.create_tool(_tool_config())
        tool.forward()

    assert entered.is_set()
    assert cancelled.wait(1)
    assert exited.wait(1)
    asyncio.run(manager.shutdown(timeout=1))


class _SlowConnectContext:
    def __init__(self, delay: float):
        self.delay = delay

    async def __aenter__(self):
        await asyncio.sleep(self.delay)
        return _BlockingAsyncSession(threading.Event(), threading.Event()), []

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False


def test_ut_sdk_mcp_connection_deadline_only_covers_session_startup():
    """The connect deadline bounds lazy session setup on first tool call."""
    manager = _manager()
    scope = RunCancellationScope()

    with _blocking_collection(
        manager, scope, None,
        tool_timeout_seconds=5, connect_timeout_seconds=0.01,
        session_context_factory=lambda *_args, **_kwargs: _SlowConnectContext(1),
    ) as collection:
        tool = collection.create_tool(_tool_config())
        with pytest.raises(MCPConnectionTimeoutError, match="0.01 seconds"):
            tool.forward()

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

    with _blocking_collection(
        manager, scope, context, tool_timeout_seconds=1,
    ) as collection:
        tool = collection.create_tool(_tool_config())
        caller = threading.Thread(
            target=_capture_cancelled,
            args=(result, tool.forward),
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


class _FailingConnectContext:
    async def __aenter__(self):
        raise ConnectionRefusedError("[Errno 111] Connection refused")

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False


class _CancelledConnectContext:
    async def __aenter__(self):
        raise asyncio.CancelledError()

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False


def test_connection_failure_is_attributed_to_server():
    """An unreachable server does not block entering; its first tool call
    surfaces MCPConnectionFailure carrying url/transport."""
    manager = _manager()
    scope = RunCancellationScope()
    with _blocking_collection(
        manager, scope, None, tool_timeout_seconds=1, connect_timeout_seconds=1,
        session_context_factory=lambda *_args, **_kwargs: _FailingConnectContext(),
    ) as collection:
        tool = collection.create_tool(_tool_config())
        with pytest.raises(MCPConnectionFailure) as exc_info:
            tool.forward()

    failure = exc_info.value
    assert failure.url == "http://mcp.invalid/mcp"
    assert failure.transport == "streamable-http"
    assert isinstance(failure.__cause__, ConnectionRefusedError)
    assert manager.snapshot().active_count == 0
    asyncio.run(manager.shutdown(timeout=1))


def test_lazy_connect_only_on_first_call_and_reuse():
    """Entering and tool construction contact no server; the first tool call
    connects once and later calls reuse the session."""
    manager = _manager()
    scope = RunCancellationScope()
    exited = threading.Event()

    class _EchoSession:
        async def call_tool(self, name, arguments):
            return (name, arguments)

    context = _AsyncMCPContext(_EchoSession(), exited)
    factory = _async_context_factory(context)

    with _blocking_collection(
        manager, scope, context, tool_timeout_seconds=1, session_context_factory=factory,
    ) as collection:
        assert factory.calls["calls"] == 0
        tool = collection.create_tool(_tool_config())
        assert factory.calls["calls"] == 0
        assert tool.forward({"value": 1}) == ("blocking_tool", {"value": 1})
        assert factory.calls["calls"] == 1
        assert tool.forward({"value": 2}) == ("blocking_tool", {"value": 2})
        assert factory.calls["calls"] == 1, "session must be reused within the run"

    assert exited.wait(1)
    assert manager.snapshot().active_count == 0
    asyncio.run(manager.shutdown(timeout=1))


def test_tool_missing_from_live_server_raises_not_found():
    """A configured tool absent from the live tool list fails the call with
    MCPToolNotFoundError instead of a protocol error."""
    manager = _manager()
    scope = RunCancellationScope()
    exited = threading.Event()

    class _EmptySession:
        async def call_tool(self, name, arguments):
            return name

    context = _AsyncMCPContext(_EmptySession(), exited)

    with _blocking_collection(manager, scope, context, tool_timeout_seconds=1) as collection:
        tool = collection.create_tool(_tool_config(
            class_name="renamed_away", name="renamed_away", origin_name="renamed_away",
        ))
        with pytest.raises(MCPToolNotFoundError, match="renamed_away"):
            tool.forward({})

    assert manager.snapshot().active_count == 0
    asyncio.run(manager.shutdown(timeout=1))


def test_close_cancels_pending_lazy_connect():
    """Closing the run while a lazy connect is in flight cancels the caller
    and tears the session loop down cleanly."""
    manager = _manager()
    scope = RunCancellationScope()
    result = {}
    collection = _blocking_collection(
        manager, scope, None, tool_timeout_seconds=5,
        session_context_factory=lambda *_args, **_kwargs: _SlowConnectContext(5),
    )
    with collection:
        tool = collection.create_tool(_tool_config())
        caller = threading.Thread(
            target=_capture_cancelled,
            args=(result, tool.forward),
        )
        caller.start()
        deadline = time.monotonic() + 1
        while not collection._active_calls and time.monotonic() < deadline:
            time.sleep(0.01)
        assert collection._active_calls, "lazy connect did not start"
        collection.close()
        caller.join(2)

    assert caller.is_alive() is False
    assert isinstance(result.get("error"), CancelledError)
    assert manager.snapshot().active_count == 0
    asyncio.run(manager.shutdown(timeout=1))


def test_connection_cancellation_is_not_wrapped():
    """Cancelling a session setup must not be disguised as an MCP failure."""
    manager = _manager()
    scope = RunCancellationScope()
    collection = _blocking_collection(
        manager, scope, None, tool_timeout_seconds=1, connect_timeout_seconds=1,
        session_context_factory=lambda *_args, **_kwargs: _CancelledConnectContext(),
    )

    async def connect_directly():
        async with AsyncExitStack() as stack:
            collection._stack = stack
            await collection._connect_server({"url": "http://mcp.invalid/mcp", "transport": "sse"})

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(connect_directly())
    asyncio.run(manager.shutdown(timeout=1))
