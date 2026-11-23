# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Preparation phases preserve real timing and parentage without repeating work."""

import asyncio
import importlib
from types import SimpleNamespace

import pytest
from nexent.monitor.phase_capture import (
    capture_preparation,
    emit_preparation,
    trace_phase,
)
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from .test_sandbox_warmup import factory as _sandbox_factory


@pytest.fixture
def sandbox_factory(mocker):
    return _sandbox_factory.__wrapped__(mocker)


@pytest.fixture
def local_spans(spans, monkeypatch):
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(spans.manager, "_tracer", provider.get_tracer("phases"))
    monkeypatch.setattr(spans.manager._config, "provider", "local_file")
    yield spans.manager, exporter
    provider.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("traced", [False, True])
async def test_preparation_keeps_strict_wire_models_serializable(local_spans, monkeypatch, traced):
    from pydantic import BaseModel, ConfigDict

    manager, exporter = local_spans
    monkeypatch.setattr(manager._config, "enable_telemetry", traced)

    class PreparedWireRun(BaseModel):
        model_config = ConfigDict(extra="forbid")
        query: str

    @capture_preparation
    async def prepare():
        with trace_phase("prepare.wire"):
            return PreparedWireRun(query="task")

    result = await prepare()
    assert result.model_dump() == {"query": "task"}
    assert result.model_dump_json() == '{"query":"task"}'
    assert not hasattr(result, "run_timing") and not hasattr(result, "preparation_trace")
    assert not exporter.get_finished_spans()


@pytest.mark.asyncio
async def test_preparation_is_emitted_once_under_worker_with_original_timing(
    local_spans, monkeypatch
):
    manager, exporter = local_spans
    calls = []

    @capture_preparation
    async def prepare():
        with trace_phase(
            "memory.presearch", input_value={"query": "问题", "api_key": "private"}
        ) as phase:
            calls.append("search")
            phase.set_output({"matches": ["结果"]})
        return SimpleNamespace()

    info = await prepare()
    assert calls == ["search"] and not exporter.get_finished_spans()
    record = next(r for r in info.preparation_trace if r["name"] == "memory.presearch")
    module = importlib.import_module("nexent.core.agents.orchestration.entry")
    info.agent_config = None
    info.query = "q"
    info.model_config_list = []
    info.history = []
    info.attempt_outcome = "completed"
    monkeypatch.setattr(module, "_agent_run_thread", lambda _, **kwargs: calls.append("run"))
    module.agent_run_thread(info)
    nodes = {s.name: s for s in exporter.get_finished_spans()}
    root, preparation, search = (
        nodes["agent.run"],
        nodes["agent.prepare"],
        nodes["memory.presearch"],
    )
    assert search.parent.span_id == preparation.context.span_id
    assert preparation.parent.span_id == root.context.span_id
    # Shared UTC boundaries retain microseconds; phase records retain nanoseconds.
    assert root.start_time // 1000 <= search.start_time // 1000 <= search.end_time // 1000 <= root.end_time // 1000
    assert (
        search.start_time == record["started_at_ns"]
        and search.end_time == record["finished_at_ns"]
    )
    assert search.attributes["nexent.node.kind"] == "phase"
    assert "private" not in search.attributes["input.value"]
    assert "结果" in search.attributes["output.value"]
    assert (
        root.attributes["nexent.duration_ms"] >= int(search.attributes["nexent.duration_ms"])
    )
    assert info.preparation_trace == [] and calls == ["search", "run"]


@pytest.mark.asyncio
async def test_concurrent_preparations_and_failed_scope_do_not_leak(local_spans):
    @capture_preparation
    async def prepare(value):
        with trace_phase("memory.presearch", input_value=value):
            await asyncio.sleep(0)
        if value == "failed":
            raise RuntimeError("private")
        return SimpleNamespace()

    first, second = await asyncio.gather(prepare("first"), prepare("second"))
    assert (
        next(r for r in first.preparation_trace if r["name"] == "memory.presearch")[
            "attributes"
        ]["input.value"]
        == "first"
    )
    assert (
        next(r for r in second.preparation_trace if r["name"] == "memory.presearch")[
            "attributes"
        ]["input.value"]
        == "second"
    )
    with pytest.raises(RuntimeError):
        await prepare("failed")
    third = await prepare("third")
    assert len(third.preparation_trace) == 2


@pytest.mark.parametrize("error", [RuntimeError, asyncio.CancelledError])
def test_live_failure_preserves_exception_without_sensitive_message(local_spans, error):
    manager, exporter = local_spans
    with manager.start_agent_run():
        with pytest.raises(error):
            with trace_phase("agent.sandbox.initialize"):
                raise error("credential-sensitive")
    node = next(
        s for s in exporter.get_finished_spans() if s.name == "agent.sandbox.initialize"
    )
    assert node.status.status_code == StatusCode.ERROR
    assert node.attributes["error.type"] == error.__name__
    assert "credential-sensitive" not in str(node.attributes) + str(node.events)
    assert trace.get_current_span().is_recording() is False


@pytest.mark.asyncio
async def test_remote_mode_does_not_attach_or_emit_phase_facts(spans):
    @capture_preparation
    async def prepare():
        with trace_phase("memory.presearch"):
            return SimpleNamespace()

    result = await prepare()
    assert not hasattr(result, "preparation_trace")
    with spans.manager.start_agent_run():
        with trace_phase("agent.sandbox.initialize"):
            pass
        emit_preparation(result)
    assert [s.name for s in spans.exporter.get_finished_spans()] == ["agent.run"]


def test_preparation_budget_and_export_failure_do_not_change_work(
    local_spans, monkeypatch
):
    from nexent.monitor import phase_capture

    records = []
    token = phase_capture._preparation.set(records)
    try:
        for _ in range(4100):
            with trace_phase("memory.initialize"):
                pass
    finally:
        phase_capture._preparation.reset(token)
    assert len(records) == 4096
    assert records[0]["attributes"]["nexent.trajectory.gap"] is True
    manager, exporter = local_spans
    with manager.start_agent_run() as root:
        monkeypatch.setattr(
            manager.tracer,
            "start_span",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError()),
        )
        with trace_phase("agent.sandbox.initialize"):
            value = 42
        emit_preparation(SimpleNamespace(preparation_trace=records[:1]))
        assert root.attributes["nexent.trajectory.gap"] is True
    assert value == 42


@pytest.mark.parametrize(
    "backend,fail", [("docker", False), ("local", False), ("docker", True)]
)
def test_actual_executor_creation_records_backend_and_failure(
    local_spans, mocker, sandbox_factory, backend, fail
):
    from .test_sandbox_warmup import config

    manager, exporter = local_spans
    build = mocker.patch("nexent.core.agents.sandbox.execution.build_python_executor")
    build.return_value = mocker.Mock(_nexent_backend=backend)
    if fail:
        build.side_effect = RuntimeError("private")
    with manager.start_agent_run():
        if fail:
            with pytest.raises(ValueError):
                sandbox_factory.create_single_agent(config())
        else:
            sandbox_factory.create_single_agent(config())
    assert build.call_count == 1
    node = next(
        s for s in exporter.get_finished_spans() if s.name == "agent.sandbox.initialize"
    )
    assert node.attributes["nexent.node.kind"] == "phase"
    assert node.attributes["nexent.duration_ms"] >= 0
    if fail:
        assert node.status.status_code == StatusCode.ERROR
        assert "private" not in str(node.attributes)
    else:
        import json

        assert json.loads(node.attributes["output.value"]) == {
            "backend": backend,
            "fallback": backend == "local",
        }


def test_workspace_initialization_only_records_actual_remote_work(
    local_spans, mocker, sandbox_factory, tmp_path
):
    manager, exporter = local_spans
    sandbox_factory.workspace_path = str(tmp_path)
    local = mocker.Mock(_nexent_backend="local")
    remote = mocker.Mock(
        _nexent_backend="docker", _nexent_kernel_recovery_supported=False
    )
    with manager.start_agent_run():
        sandbox_factory._initialize_sandbox_workspaces([local])
        sandbox_factory._initialize_sandbox_workspaces([remote])
    nodes = [
        s for s in exporter.get_finished_spans() if s.name == "agent.sandbox.workspace"
    ]
    assert len(nodes) == 1 and nodes[0].status.status_code == StatusCode.OK
    local.assert_not_called()
    remote.assert_called_once()


@pytest.mark.asyncio
async def test_optional_telemetry_dependency_absent_keeps_business_behavior(
    monkeypatch,
):
    import builtins
    import importlib.util
    from pathlib import Path

    from nexent.monitor import phase_capture

    original = builtins.__import__

    def without_otel(name, *args, **kwargs):
        if name == "opentelemetry" or name.startswith("opentelemetry."):
            raise ImportError("optional telemetry unavailable")
        return original(name, *args, **kwargs)

    spec = importlib.util.spec_from_file_location(
        "nexent.monitor.phase_without_otel", Path(phase_capture.__file__)
    )
    module = importlib.util.module_from_spec(spec)
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "__import__", without_otel)
        spec.loader.exec_module(module)
    assert module.trace is None

    @module.capture_preparation
    async def prepare():
        with module.trace_phase("memory.presearch") as phase:
            phase.set_output("result")
            return SimpleNamespace(value=42)

    result = await prepare()
    assert result.value == 42 and not hasattr(result, "preparation_trace")
    assert module.preparation_start(result) is None
    module.emit_preparation(result)


def test_deferred_executor_has_no_initialization_phase_until_acquired(
    local_spans, mocker, sandbox_factory
):
    from .test_sandbox_warmup import config

    manager, exporter = local_spans
    sandbox_factory.tool_fastpath_enabled = True
    build = mocker.patch("nexent.core.agents.sandbox.execution.build_python_executor")
    build.return_value = mocker.Mock(_nexent_backend="docker")
    with manager.start_agent_run():
        agent = sandbox_factory.create_single_agent(config())
        build.assert_not_called()
        assert not any(
            s.name == "agent.sandbox.initialize" for s in exporter.get_finished_spans()
        )
        agent.executor("import math; result = math.sqrt(4)")
    build.assert_called_once()
    phases = [
        s for s in exporter.get_finished_spans() if s.name == "agent.sandbox.initialize"
    ]
    assert len(phases) == 1


@pytest.mark.parametrize("fail", [False, True])
def test_memory_retrieval_records_error_before_tool_degrades(local_spans, fail):
    from unittest.mock import AsyncMock

    from nexent.core.tools.search_memory_tool import SearchMemoryTool

    manager, exporter = local_spans
    service = SimpleNamespace(build_context=AsyncMock(
        side_effect=RuntimeError("private") if fail else None,
        return_value=SimpleNamespace(tenant_long_term=[], user_long_term=[], agent_short_term=[], external=[]),
    ))
    tool = SearchMemoryTool(
        memory_service=None, memory_context_service=service, tenant_id="tenant", user_id="owner",
        agent_id="7", conversation_id="123", embedding_configured=True, external_results=[],
    )
    with manager.start_agent_run():
        result = tool.forward("controlled", 5)
    service.build_context.assert_awaited_once()
    node = next(s for s in exporter.get_finished_spans() if s.name == "memory.retrieve")
    assert node.attributes["nexent.node.kind"] == "phase"
    assert node.status.status_code == (StatusCode.ERROR if fail else StatusCode.OK)
    assert "private" not in str(node.attributes)
    assert result == ("Memory search failed. Continuing without memory results." if fail else "No relevant memories found.")
