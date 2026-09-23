"""UT-SDK-TRACE-001/002: admission and complete worker span lifetime."""

import importlib
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from opentelemetry import trace

from nexent.core.concurrency import (
    ManagedTaskSpec,
    RunCancellationScope,
    get_current_thread_manager,
)
from nexent.monitor import (
    AgentRunMetadata,
    agent_monitoring_context,
    get_agent_monitoring_context,
)

from .conftest import assert_child, by_name

run_module = importlib.import_module("nexent.core.agents.run_agent")


def test_ut_sdk_trace_001_deferred_binding_restores_request_and_worker_manager(spans, threads, monkeypatch):
    deferred = run_module.DeferredAgentRun()
    info = SimpleNamespace(cancellation_scope=RunCancellationScope())
    seen = {}

    def worker(_info):
        seen["manager"] = get_current_thread_manager()
        seen["metadata"] = get_agent_monitoring_context()
        with spans.tracer.start_as_current_span("worker"):
            pass

    monkeypatch.setattr(run_module, "agent_run_thread", worker)
    execution = threads.submit(
        "agent-run", ManagedTaskSpec("deferred", "test", pass_cancel_event=True), deferred.run
    )
    assert execution.started_event.wait(1)
    metadata = AgentRunMetadata(tenant_id="tenant-new", conversation_id=42)
    with spans.tracer.start_as_current_span("request"), agent_monitoring_context(metadata):
        deferred.bind(info)
        execution.future.result(timeout=2)

    assert seen == {"manager": threads, "metadata": metadata}
    assert get_agent_monitoring_context() is None
    assert get_current_thread_manager() is None
    tree = by_name(spans)
    assert_child(tree["worker"], tree["request"])


@pytest.mark.parametrize("cancel_before_bind", [True, False])
def test_ut_sdk_trace_001_cancelled_deferred_never_runs(spans, monkeypatch, cancel_before_bind):
    deferred = run_module.DeferredAgentRun()
    info = SimpleNamespace(cancellation_scope=RunCancellationScope())
    calls = []
    monkeypatch.setattr(run_module, "agent_run_thread", lambda _info: calls.append(_info))
    if cancel_before_bind:
        deferred.cancel()
    deferred.bind(info)
    if not cancel_before_bind:
        deferred.cancel()
    deferred.run(threading.Event())
    assert info.cancellation_scope.cancelled
    assert not calls
    with pytest.raises(RuntimeError, match="already bound"):
        deferred.bind(info)


@pytest.mark.parametrize("with_mcp", [False, True])
@pytest.mark.parametrize("fail_phase", [None, "construct", "loop"])
def test_ut_sdk_trace_002_worker_span_includes_setup_and_cleanup(
    spans, threads, monkeypatch, mocker, with_mcp, fail_phase
):
    info = SimpleNamespace(
        query="test", model_config_list=[], observer=mocker.Mock(lang="en"),
        agent_config=SimpleNamespace(name="root", display_name="主助手", context_items=None),
        mcp_host=["http://mcp.invalid/mcp"] if with_mcp else [],
        stop_event=threading.Event(), cancellation_scope=RunCancellationScope(),
        redis_client=None, conversation_id=42, user_id="user", tenant_id="tenant",
        workspace_path=None, workspace_run_id=None,
        history=[], runtime_metadata={}, thread_manager=threads,
        mcp_tool_timeout_seconds=1, mcp_close_timeout_seconds=1,
    )

    def phase(name):
        with spans.tracer.start_as_current_span(name):
            if name == fail_phase:
                raise RuntimeError(f"{name} failed")

    instance = mocker.Mock()
    instance.create_single_agent.side_effect = lambda *a, **k: phase("construct")
    instance.add_history_to_agent.side_effect = lambda *a: phase("history")

    def loop(**kwargs):
        with spans.manager.start_agent_run():
            phase("loop")

    instance.agent_run_with_observer.side_effect = loop

    def create(**kwargs):
        phase("initialize")
        return instance

    @contextmanager
    def mcp(**kwargs):
        phase("mcp-connect")
        try:
            yield SimpleNamespace(tools=[])
        finally:
            phase("mcp-close")

    monkeypatch.setattr(run_module, "NexentAgent", create)
    monkeypatch.setattr(run_module, "ManagedMCPToolCollection", mcp)
    monkeypatch.setattr(run_module, "cleanup_run_workspace", lambda *a: phase("cleanup"))
    monkeypatch.setattr(run_module, "_log_memory_value_assessment", lambda *a: None)
    with spans.tracer.start_as_current_span("request"), agent_monitoring_context(
        AgentRunMetadata(agent_id=1, tenant_id="tenant", conversation_id=42)
    ):
        parent = trace.get_current_span()
        if fail_phase:
            with pytest.raises(ValueError, match=f"{fail_phase} failed"):
                run_module.agent_run_thread(info)
        else:
            run_module.agent_run_thread(info)
        assert trace.get_current_span() is parent

    exported = spans.exporter.get_finished_spans()
    assert sum(s.name == "agent.run" for s in exported) == 1
    tree = by_name(spans)
    root = tree["agent.run"]
    assert_child(root, tree["request"])
    assert root.attributes["agent.name"] == "root"
    assert root.attributes["langfuse.trace.name"] == "主助手"
    for name, span in tree.items():
        if name not in {"request", "agent.run"}:
            assert_child(span, root)
    assert "cleanup" in tree
    assert root.status.is_ok == (fail_phase is None)
