"""UT-SDK-TRACE-003/004/006/007 and local HTTP bridge integration."""

import logging
import threading
from contextvars import ContextVar
from types import SimpleNamespace

import pytest
from nexent.core.agents import sandbox
from nexent.core.concurrency import ManagedTaskSpec, get_current_thread_manager
from nexent.core.tools.parallel_executor import _parallel_executor
from nexent.monitor import (
    AgentRunMetadata,
    agent_monitoring_context,
    get_agent_monitoring_context,
)

from .conftest import assert_child, by_name


@pytest.fixture
def bridge(threads, monkeypatch):
    monkeypatch.setattr(sandbox, "_get_sandbox_thread_manager", lambda: threads)
    instance = sandbox._ToolBridge(logging.getLogger(__name__))
    yield instance
    instance.close()


def payload(execution_id, tool="echo", **kwargs):
    return {"tool": tool, "args": [], "kwargs": kwargs, "execution_id": execution_id}


def test_ut_sdk_trace_003_callback_uses_execution_context(spans, bridge, threads):
    observed = []

    def echo(value):
        observed.append(get_agent_monitoring_context())
        with spans.tracer.start_as_current_span("callback"):
            return value

    bridge.register({"echo": echo})
    metadata = AgentRunMetadata(tenant_id="tenant", conversation_id=42)
    with (
        spans.tracer.start_as_current_span("python"), agent_monitoring_context(metadata),
        bridge.execution_context() as execution_id,
    ):
        request_payload = payload(execution_id, value="answer")
        execution = threads.submit(
            "model-tool-io", ManagedTaskSpec("callback", "test"), bridge._invoke_tool, request_payload
        )
        assert execution.future.result(timeout=2) == "answer"
    tree = by_name(spans)
    assert_child(tree["callback"], tree["python"])
    assert observed == [metadata]


def test_ut_sdk_trace_004_parallel_callbacks_get_independent_context_copies(spans, bridge, threads):
    local = ContextVar("bridge-test-value", default="unset")
    barrier = threading.Barrier(2, timeout=2)

    def echo(value):
        assert local.get() == "snapshot"
        local.set(value)
        barrier.wait()
        with spans.tracer.start_as_current_span(value):
            return local.get()

    bridge.register({"echo": echo})
    token = local.set("snapshot")
    try:
        with spans.tracer.start_as_current_span("python"), bridge.execution_context() as execution_id:
            executions = [
                threads.submit(
                    "model-tool-io", ManagedTaskSpec("callback", "test"),
                    bridge._invoke_tool, payload(execution_id, value=value),
                )
                for value in ("a", "b")
            ]
            assert [execution.future.result(timeout=3) for execution in executions] == ["a", "b"]
        assert local.get() == "snapshot"
    finally:
        local.reset(token)
    tree = by_name(spans)
    for name in ("a", "b"):
        assert_child(tree[name], tree["python"])


@pytest.mark.parametrize("exit_mode", ["normal", "error", "close"])
def test_ut_sdk_trace_004_expired_ids_never_execute_under_later_context(spans, bridge, exit_mode):
    calls = []
    bridge.register({"echo": lambda: calls.append("called")})
    try:
        with bridge.execution_context() as expired:
            if exit_mode == "error":
                raise ValueError("controlled")
            if exit_mode == "close":
                bridge.close()
    except ValueError:
        pass
    with spans.tracer.start_as_current_span("later"):
        with pytest.raises(ValueError, match="execution context"):
            bridge._invoke_tool(payload(expired))
        with pytest.raises(ValueError, match="execution context"):
            bridge._invoke_tool(payload("unknown"))
    assert not calls


class LocalKernel:
    """Run only fixed test code while keeping the real HTTP proxy boundary."""

    def __init__(self):
        self.namespace = {}

    def send_tools(self, tools):
        assert not tools

    def run_code_raise_errors(self, code):
        exec(code, self.namespace)  # noqa: S102 - Fixed bridge bootstrap in an isolated test namespace.
        return SimpleNamespace(logs="")

    def __call__(self, code):
        exec(code, self.namespace)  # noqa: S102 - Fixed test program; no model-generated code.
        return self.namespace.get("result")

    def cleanup(self):
        pass


def test_bridge_http_execution_refreshes_proxy_and_preserves_parallel_tree(spans, threads, monkeypatch):
    """Local HTTP integration: actual proxy, handler, tool wrappers and worker pool."""
    monkeypatch.setattr(sandbox, "_get_sandbox_thread_manager", lambda: threads)
    executor = LocalKernel()
    seen = []

    def echo(value):
        with spans.tracer.start_as_current_span(f"echo-{value}"):
            seen.append((value, get_agent_monitoring_context().conversation_id, get_current_thread_manager()))
            return value

    def parallel(tasks):
        with spans.tracer.start_as_current_span("parallel"):
            return _parallel_executor(tasks)

    echo._nexent_execute_on_host = True
    parallel._nexent_execute_on_host = True
    sandbox._install_host_tool_bridge(executor, logging.getLogger(__name__))
    executor.send_tools({"echo": echo, "parallel": parallel})
    try:
        def run(conversation_id):
            with spans.tracer.start_as_current_span(f"python-{conversation_id}"), agent_monitoring_context(
                AgentRunMetadata(conversation_id=conversation_id)
            ):
                return sandbox._execute_with_tool_context(
                    executor,
                    "saved = echo\nresult = parallel([(echo, {'value': 'a'}), (echo, {'value': 'b'})])"
                    if conversation_id == 1 else "result = echo(value='c')",
                )

        first = threads.submit("agent-run", ManagedTaskSpec("run", "test"), run, 1)
        assert first.future.result(timeout=4) == ["a", "b"]
        old_proxy = executor.namespace["saved"]
        second = threads.submit("agent-run", ManagedTaskSpec("run", "test"), run, 2)
        assert second.future.result(timeout=4) == "c"
        with pytest.raises(RuntimeError, match="execution context"):
            old_proxy(value="stale")
        tree = by_name(spans)
        assert_child(tree["parallel"], tree["python-1"])
        for name in ("echo-a", "echo-b"):
            assert_child(tree[name], tree["parallel"])
        assert_child(tree["echo-c"], tree["python-2"])
        assert tree["python-1"].context.trace_id != tree["python-2"].context.trace_id
        assert sorted(seen, key=lambda item: item[0]) == [("a", 1, threads), ("b", 1, threads), ("c", 2, threads)]
    finally:
        executor.cleanup()


def test_ut_sdk_trace_007_bridge_without_monitoring(spans, bridge, monkeypatch):
    monkeypatch.setattr(spans.manager, "_config", None)
    bridge.register({"echo": lambda value: value})
    with bridge.execution_context() as execution_id:
        assert bridge._invoke_tool(payload(execution_id, value=42)) == 42
    assert not spans.exporter.get_finished_spans()


def test_ut_sdk_trace_007_local_executor_needs_no_bridge():
    assert sandbox._execute_with_tool_context(lambda code: code, "unchanged") == "unchanged"


def test_bridge_http_two_concurrent_runs_do_not_share_context(spans, threads, monkeypatch):
    """Two isolated kernel leases overlap their real HTTP tool callbacks."""
    monkeypatch.setattr(sandbox, "_get_sandbox_thread_manager", lambda: threads)
    barrier = threading.Barrier(2, timeout=3)
    executors = [LocalKernel(), LocalKernel()]
    seen = []

    def echo(value):
        barrier.wait()
        with spans.tracer.start_as_current_span(f"echo-{value}"):
            seen.append((value, get_agent_monitoring_context().conversation_id))
            return value

    echo._nexent_execute_on_host = True

    def run(index):
        with spans.tracer.start_as_current_span(f"request-{index}"), agent_monitoring_context(
            AgentRunMetadata(conversation_id=index)
        ):
            return sandbox._execute_with_tool_context(executors[index], f"result = echo(value={index})")

    try:
        for executor in executors:
            sandbox._install_host_tool_bridge(executor, logging.getLogger(__name__))
            executor.send_tools({"echo": echo})
        executions = [
            threads.submit("agent-run", ManagedTaskSpec("concurrent-run", "test"), run, index)
            for index in range(2)
        ]
        assert [execution.future.result(timeout=5) for execution in executions] == [0, 1]
        assert sorted(seen) == [(0, 0), (1, 1)]
        tree = by_name(spans)
        for index in range(2):
            assert_child(tree[f"echo-{index}"], tree[f"request-{index}"])
        assert tree["request-0"].context.trace_id != tree["request-1"].context.trace_id
    finally:
        for executor in executors:
            executor.cleanup()


def test_ut_sdk_trace_004_executor_failure_retires_proxy_context(threads, monkeypatch):
    monkeypatch.setattr(sandbox, "_get_sandbox_thread_manager", lambda: threads)
    executor = LocalKernel()
    calls = []

    def echo():
        calls.append("called")

    echo._nexent_execute_on_host = True
    sandbox._install_host_tool_bridge(executor, logging.getLogger(__name__))
    executor.send_tools({"echo": echo})
    try:
        with pytest.raises(ValueError, match="execution failed"):
            sandbox._execute_with_tool_context(executor, "raise ValueError('execution failed')")
        assert not executor._nexent_tool_bridge._execution_contexts
        with pytest.raises(RuntimeError, match="execution context"):
            executor.namespace["echo"]()
        assert not calls
    finally:
        executor.cleanup()


def test_ut_sdk_trace_004_rebinding_tools_cannot_change_an_admitted_callback(bridge):
    bridge.register({"echo": lambda: "original tool"})
    with bridge.execution_context() as first:
        bridge.register({"echo": lambda: "replacement tool"})
        assert bridge._invoke_tool(payload(first)) == "original tool"
    with bridge.execution_context() as second:
        assert bridge._invoke_tool(payload(second)) == "replacement tool"


def test_ut_sdk_trace_003_execution_preserves_future_imports(threads, monkeypatch):
    monkeypatch.setattr(sandbox, "_get_sandbox_thread_manager", lambda: threads)
    executor = LocalKernel()

    def echo(value):
        return value

    echo._nexent_execute_on_host = True
    sandbox._install_host_tool_bridge(executor, logging.getLogger(__name__))
    executor.send_tools({"echo": echo})
    try:
        assert sandbox._execute_with_tool_context(
            executor, "from __future__ import annotations\nresult = echo(value=42)",
        ) == 42
    finally:
        executor.cleanup()
