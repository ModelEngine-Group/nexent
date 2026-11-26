# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import asyncio
import threading
import time
import types
from concurrent.futures import CancelledError
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import AsyncExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock

import mcp.types
import mcpadapt.core
import pytest
from nexent.consts.mcp_errors import (
    MCPConnectionFailure,
    MCPConnectionTimeoutError,
    MCPToolNotFoundError,
    MCPToolResultError,
    MCPToolTimeoutError,
)
from nexent.core.agents.contracts.config import ToolConfig
from nexent.core.agents.resources.mcp import ManagedMCPToolCollection
from nexent.core.concurrency import LanePolicy, RunCancellationScope, ThreadManager
from nexent.monitor.facts import set_fact_sink
from nexent.monitor.monitoring import AgentRunMetadata, agent_monitoring_context


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


class _CompletedAsyncSession:
    async def call_tool(self, name, arguments):
        return {"ok": True}


class _AsyncMCPContext:
    def __init__(self, session, exited: threading.Event, name: str = "blocking_tool"):
        self.session = session
        self.exited = exited
        self.name = name
        self.exit_count = 0

    async def __aenter__(self):
        tool = mcp.types.Tool(
            name=self.name,
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


def test_tool_result_callback_is_bound_to_its_server():
    class Session:
        async def call_tool(self, name, arguments):
            return mcp.types.CallToolResult(
                content=[mcp.types.TextContent(type="text", text="public output")],
                _meta={"receipt": name},
            )

    manager = _manager()
    receipt = MagicMock()
    local = _AsyncMCPContext(Session(), threading.Event(), "local_tool")
    remote = _AsyncMCPContext(Session(), threading.Event(), "remote_tool")

    def factory(parameters, **kwargs):
        assert "on_tool_result" not in parameters
        return local if parameters["url"] == "local" else remote

    def builder(tool_config, call_fn):
        tool = types.SimpleNamespace(name=tool_config.class_name)

        def forward(arguments=None, **_kwargs):
            # Mirror the smolagents adapter rendering: text content only.
            result = call_fn(arguments)
            return result.content[0].text

        tool.forward = forward
        return tool

    try:
        with ManagedMCPToolCollection(
            manager=manager,
            server_parameters=[{"url": "local", "on_tool_result": receipt}, {"url": "remote"}],
            cancellation_scope=RunCancellationScope(),
            tool_timeout_seconds=1,
            close_timeout_seconds=0.5,
            session_context_factory=factory,
            tool_builder=builder,
        ) as collection:
            local_tool = collection.create_tool(
                _tool_config(class_name="local_tool", name="local_tool",
                             origin_name="local_tool", usage="local")
            )
            remote_tool = collection.create_tool(
                _tool_config(class_name="remote_tool", name="remote_tool",
                             origin_name="remote_tool", usage="remote")
            )
            assert remote_tool.forward() == "public output"
            receipt.assert_not_called()
            assert local_tool.forward() == "public output"
            receipt.assert_called_once_with("local_tool", {"receipt": "local_tool"})
    finally:
        asyncio.run(manager.shutdown(timeout=1))


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


@pytest.mark.parametrize("missing", [False, True])
def test_prepared_mcp_discovery_only_exposes_names_authorized_for_each_server(missing):
    """Lazy sessions keep develop's per-server authorization guards.

    Connections open at first tool call, allowed_tools never reach the
    session factory, and a server whose discovery lost an authorized name
    fails exactly the tools that route to it — other servers stay usable.
    """
    from contextlib import asynccontextmanager

    manager = _manager()
    seen_parameters = []

    class _RecordingSession:
        async def call_tool(self, name, arguments):
            return (name, arguments)

    @asynccontextmanager
    async def sessions(parameters, **_kwargs):
        assert "allowed_tools" not in parameters
        seen_parameters.append(parameters["url"])
        first = parameters["url"] == "http://first.invalid/mcp"
        names = ["own-first", "own_second"] if first else ["own-first"]
        if not first and not missing:
            names.append("own_second")
        discovered = [
            mcp.types.Tool(name=name, description=parameters["url"], inputSchema={"type": "object", "properties": {}})
            for name in names
        ]
        yield _RecordingSession(), discovered

    scope = RunCancellationScope()
    try:
        collection = ManagedMCPToolCollection(
            manager=manager,
            server_parameters=[
                {"url": "http://first.invalid/mcp", "allowed_tools": {"own-first": "own_first"}},
                {"url": "http://second.invalid/mcp", "allowed_tools": {"own_second": "own_second"}},
            ],
            cancellation_scope=scope, tool_timeout_seconds=1, close_timeout_seconds=0.5,
            session_context_factory=sessions, tool_builder=_fake_builder,
        )
        first_tool = collection.create_tool(
            _tool_config(class_name="own_first", origin_name="own-first", usage="http://first.invalid/mcp")
        )
        second_tool = collection.create_tool(
            _tool_config(class_name="own_second", origin_name="own_second", usage="http://second.invalid/mcp")
        )
        # Entering the collection opens no connections; tools are inert.
        with collection:
            assert collection.tools == [first_tool, second_tool]
            assert seen_parameters == []
            assert first_tool.forward({}) == ("own-first", {})
            if missing:
                # The second server's discovery lost the authorized name, so
                # only tools routed to it fail; the first server is unaffected.
                with pytest.raises(ValueError, match="missing from discovery"):
                    second_tool.forward({})
                assert seen_parameters == ["http://first.invalid/mcp", "http://second.invalid/mcp"]
            else:
                assert second_tool.forward({}) == ("own_second", {})
                assert seen_parameters == ["http://first.invalid/mcp", "http://second.invalid/mcp"]
        assert manager.snapshot().active_count == 0
    finally:
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


def _metadata(**overrides):
    values = {
        "tenant_id": "tenant-1",
        "agent_id": 7,
        "monitoring_run_id": "run-1",
        "monitoring_root_run_id": "root-1",
        "monitoring_group_ids": (1, 2),
        "is_debug": False,
    }
    values.update(overrides)
    return AgentRunMetadata(**values)


def test_mcp_tool_call_emits_one_caller_observed_fact():
    manager = _manager()
    scope = RunCancellationScope()
    exited = threading.Event()
    context = _AsyncMCPContext(_CompletedAsyncSession(), exited)
    facts = []
    set_fact_sink(facts.append)
    try:
        with (
            ManagedMCPToolCollection(
                manager=manager,
                server_parameters=[{"url": "http://mcp.invalid/mcp"}],
                cancellation_scope=scope,
                tool_timeout_seconds=1,
                close_timeout_seconds=0.5,
                tool_builder=_fake_builder,
                session_context_factory=_async_context_factory(context),
            ) as collection,
            agent_monitoring_context(_metadata()),
        ):
            tool = collection.create_tool(_tool_config())
            result = tool.forward(value="secret-tool-argument")
    finally:
        set_fact_sink(None)
        asyncio.run(manager.shutdown(timeout=1))

    assert result == {"ok": True}
    assert exited.is_set()
    assert [fact["record_revision"] for fact in facts] == [1, 2]
    assert [fact["outcome"] for fact in facts] == ["started", "succeeded"]
    assert facts[1]["fact_id"] == facts[0]["fact_id"]
    assert facts[0]["tool_name"] == "blocking_tool"
    assert facts[0]["tenant_id"] == "tenant-1"
    assert facts[0]["agent_id"] == 7
    assert facts[0]["agent_run_id"] == "run-1"
    assert facts[0]["root_run_id"] == "root-1"
    assert facts[0]["initiator_group_ids"] == (1, 2)
    assert "secret-tool-argument" not in str(facts)


def test_mcp_tool_timeout_emits_single_failed_fact():
    manager = _manager()
    scope = RunCancellationScope()
    entered = threading.Event()
    cancelled = threading.Event()
    exited = threading.Event()
    context = _AsyncMCPContext(_BlockingAsyncSession(entered, cancelled), exited)
    facts = []
    set_fact_sink(facts.append)
    try:
        with (
            ManagedMCPToolCollection(
                manager=manager,
                server_parameters=[{"url": "http://mcp.invalid/mcp"}],
                cancellation_scope=scope,
                tool_timeout_seconds=0.02,
                close_timeout_seconds=0.5,
                request_timeout_seconds=10,
                tool_builder=_fake_builder,
                session_context_factory=_async_context_factory(context),
            ) as collection,
            agent_monitoring_context(_metadata()),
            pytest.raises(MCPToolTimeoutError, match="0.02 seconds"),
        ):
            collection.create_tool(_tool_config()).forward()
    finally:
        set_fact_sink(None)
        asyncio.run(manager.shutdown(timeout=1))

    assert entered.is_set()
    assert cancelled.wait(1)
    assert exited.wait(1)
    assert [fact["record_revision"] for fact in facts] == [1, 2]
    assert facts[0]["outcome"] == "started"
    assert facts[1]["outcome"] == "failed"
    assert facts[1]["error_category"] == "TIMEOUT"
    assert facts[1]["fact_id"] == facts[0]["fact_id"]


class _ResultErrorSession:
    """Return a protocol-level tool error exactly as FastMCP/MCP sends it."""

    async def call_tool(self, name, arguments):
        return SimpleNamespace(isError=True, content=[])


class _MixedResultSession:
    """Succeed or fail per invocation so concurrent calls must stay distinct."""

    async def call_tool(self, name, arguments):
        failed = bool((arguments or {}).get("fail"))
        return SimpleNamespace(isError=failed, content=[])


def test_mcp_tool_is_error_result_emits_failed_fact_without_changing_result():
    manager = _manager()
    scope = RunCancellationScope()
    exited = threading.Event()
    context = _AsyncMCPContext(_ResultErrorSession(), exited)
    facts = []
    set_fact_sink(facts.append)
    try:
        with (
            ManagedMCPToolCollection(
                manager=manager,
                server_parameters=[{"url": "http://mcp.invalid/mcp"}],
                cancellation_scope=scope,
                tool_timeout_seconds=1,
                close_timeout_seconds=0.5,
                tool_builder=_fake_builder,
                session_context_factory=_async_context_factory(context),
            ) as collection,
            agent_monitoring_context(_metadata()),
        ):
            tool = collection.create_tool(_tool_config())
            result = tool.forward(value="secret-tool-argument")
    finally:
        set_fact_sink(None)
        asyncio.run(manager.shutdown(timeout=1))

    assert result.isError is True
    assert [fact["outcome"] for fact in facts] == ["started", "failed"]
    assert facts[1]["error_category"] == "TOOL_ERROR"
    assert facts[1]["fact_id"] == facts[0]["fact_id"]
    assert "secret-tool-argument" not in str(facts)


def test_mcp_tool_result_errors_are_tracked_per_invocation():
    from concurrent.futures import ThreadPoolExecutor

    manager = _manager()
    scope = RunCancellationScope()
    exited = threading.Event()
    context = _AsyncMCPContext(_MixedResultSession(), exited)
    facts = []
    set_fact_sink(facts.append)
    try:
        with (
            ManagedMCPToolCollection(
                manager=manager,
                server_parameters=[{"url": "http://mcp.invalid/mcp"}],
                cancellation_scope=scope,
                tool_timeout_seconds=5,
                close_timeout_seconds=0.5,
                tool_builder=_fake_builder,
                session_context_factory=_async_context_factory(context),
            ) as collection,
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            tool = collection.create_tool(_tool_config())

            def invoke(arguments):
                # The monitoring context is a context variable, so each worker
                # enters its own before the observed call.
                with agent_monitoring_context(_metadata()):
                    return tool.forward(arguments)

            outcomes = [
                pool.submit(invoke, {"fail": True}),
                pool.submit(invoke, {"fail": False}),
            ]
            results = [future.result(timeout=5) for future in outcomes]
    finally:
        set_fact_sink(None)
        asyncio.run(manager.shutdown(timeout=1))

    assert [result.isError for result in results] == [True, False]
    terminal = [fact for fact in facts if fact["record_revision"] == 2]
    assert sorted(fact["outcome"] for fact in terminal) == ["failed", "succeeded"]
