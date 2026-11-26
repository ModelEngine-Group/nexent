# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise the actual backend bootstrap in an isolated telemetry process."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from infrastructure.trace.trajectory_store import TrajectoryFileStore


@pytest.mark.parametrize(
    "local, remote, sampled, provider",
    [
        (True, False, True, "local_file"),
        (True, False, True, "otlp"),
        (False, True, True, "otlp"),
        (True, True, True, "otlp"),
        (True, True, False, "otlp"),
        (False, False, True, "local_file"),
        (False, False, True, "otlp"),
    ],
    ids=["local", "local-with-remote-disabled", "remote", "both", "both-unsampled", "disabled", "read-only"],
)
def test_backend_bootstrap_routes_agent_model_and_tool_traces(tmp_path, local, remote, sampled, provider):
    TrajectoryFileStore.provision(tmp_path)
    root = Path(__file__).resolve().parents[3]
    code = r"""
import asyncio
import importlib.abc
import json
import socket
import sys
from contextlib import nullcontext
from unittest.mock import patch
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


class BlockManagement(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"management", "backend.management"} or fullname.startswith(("management.", "backend.management.")):
            raise ModuleNotFoundError(f"No module named {fullname!r}", name=fullname)


sys.meta_path.insert(0, BlockManagement())
local, remote, sampled = (value == "true" for value in sys.argv[1:])
exporter = InMemorySpanExporter()
exporter_factory = patch("nexent.monitor.monitoring.OTLPSpanExporterHTTP", return_value=exporter).start()

def forbid_network(*args, **kwargs):
    raise AssertionError("The controlled exporter uses no external connections")

socket.socket.connect = forbid_network
# PG remains a controlled external boundary for this bootstrap unit test.
from infrastructure.rdb.trajectory.repository import ExecutionRepository
begin_execution = patch.object(ExecutionRepository, "begin", return_value=1).start()
patch.object(ExecutionRepository, "initialize", side_effect=lambda _: nullcontext()).start()
patch.object(ExecutionRepository, "expire", return_value=None).start()
from infrastructure.trace.bootstrap import monitoring_manager
from runtime.trajectory import configure_runtime_trajectory

assert monitoring_manager.is_enabled is remote
remote_provider = monitoring_manager._tracer_provider
existing_tracer = trace.get_tracer("startup.example")
local_trajectory_processor = configure_runtime_trajectory()
from nexent.core.concurrency import LanePolicy, ManagedThreadSpec, ThreadManager
from nexent.monitor import AgentRunMetadata
from nexent.monitor.model_attempt import ModelAttemptSession

assert monitoring_manager.is_enabled is (local or remote)
assert exporter_factory.call_count == int(remote)
if remote:
    assert monitoring_manager._tracer_provider is remote_provider
assert local_trajectory_processor is not None
# The DB collaborator is isolated; actual spans, configuration and file I/O run for real.
local_trajectory_processor.store.authorize = lambda identity: None
manager = ThreadManager("trajectory-bootstrap", {"background-service": LanePolicy("background-service", 1, 0)})
manager.start()
local_trajectory_processor.start(manager, ManagedThreadSpec("trajectory-file-writer", "test", close_hook=local_trajectory_processor.request_stop))
try:
    with monitoring_manager.start_agent_run(AgentRunMetadata(tenant_id="tenant", user_id="user", agent_id=42, conversation_id=123, query="完整问题")):
        monitoring_manager.set_openinference_agent_context(tenant_id="tenant", user_id="user", agent_id=42,
                                                         conversation_id=123, query="完整问题")
        with monitoring_manager.trace_llm_request("model.request", "test-model", **{"input.value": {"messages": [{"content": "完整请求" * 10000}]}}) as logical:
            attempt = ModelAttemptSession(monitoring_manager, "test-model", logical, "request", 1)
            tracker = attempt.begin({"messages": [{"content": "本地专用请求"}]})
            if tracker:
                tracker.record_token("完整输出")
            elif remote:
                monitoring_manager.create_token_tracker("test-model", logical).record_token("完整输出")
            attempt.end()
            monitoring_manager.set_openinference_output("完整模型输出" * 10000)
        with monitoring_manager.trace_tool_call("lookup", "agent", {"query": "工具输入"}):
            monitoring_manager.set_tool_output({"answer": "完整工具输出" * 10000})
        monitoring_manager.set_openinference_output("最终答案")
        if remote:
            with existing_tracer.start_as_current_span("startup.cached.tracer"):
                pass
    assert local_trajectory_processor.force_flush(5000)
    begin_execution.assert_called_once()
    assert begin_execution.call_args.kwargs["capturing"] is local
    documents = [json.loads(line) for path in local_trajectory_processor.store.root.rglob("*.otlp.jsonl") for line in path.read_text().splitlines()]
    spans = {span["name"]: span for doc in documents for resource in doc["resourceSpans"] for scope in resource["scopeSpans"] for span in scope["spans"]}
    assert bool(spans) is local
    def attributes(span):
        return {a["key"]: next(iter(a["value"].values())) for a in span["attributes"]}
    if local:
        assert {"agent.run", "model.request", "model.attempt", "agent.tool.lookup"} <= set(spans)
        assert "完整请求" * 10000 in attributes(spans["model.request"])["input.value"]
        assert "本地专用请求" in attributes(spans["model.attempt"])["input.value"]
        assert attributes(spans["model.request"])["output.value"] == "完整模型输出" * 10000
        assert "完整工具输出" * 10000 in attributes(spans["agent.tool.lookup"])["output.value"]
        assert attributes(spans["agent.run"])["output.value"] == "最终答案"
        assert all(event["name"] != "token_generated" for span in spans.values() for event in span.get("events", []))
        if remote:
            assert "startup.cached.tracer" in spans
    if remote_provider:
        assert remote_provider.force_flush()
    exported = {span.name: span for span in exporter.get_finished_spans()}
    assert bool(exported) is (remote and sampled)
    if exported:
        assert {"agent.run", "model.request", "agent.tool.lookup", "startup.cached.tracer"} <= set(exported)
        assert "model.attempt" not in exported
        assert not any(name.startswith("nexent.local.") for span in exported.values() for name in span.attributes)
        assert "nexent.owner_user_id" not in exported["agent.run"].attributes
        assert "trajectory_id" not in exported["agent.run"].attributes["metadata"]
        assert "完整请求" * 10000 not in exported["model.request"].attributes["input.value"]
        assert any(event.name == "token_generated" for event in exported["model.request"].events)
        if local:
            assert spans["agent.run"]["traceId"] == f'{exported["agent.run"].context.trace_id:032x}'
            assert spans["agent.run"]["spanId"] == f'{exported["agent.run"].context.span_id:016x}'
finally:
    local_trajectory_processor.shutdown()
    if monitoring_manager._tracer_provider:
        monitoring_manager._tracer_provider.shutdown()
    if monitoring_manager._meter_provider:
        monitoring_manager._meter_provider.shutdown()
    asyncio.run(manager.shutdown(timeout=2))
assert manager.snapshot().active_count == 0
"""
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(root / "backend"), str(root / "sdk")]),
        "ENABLE_TELEMETRY": str(remote or (local and provider == "local_file")).lower(),
        "LOCAL_FILE_MONITORING_ENABLED": str(local).lower(),
        "MONITORING_PROVIDER": provider,
        "OTEL_TRACES_SAMPLER": "always_on" if sampled else "always_off",
        "OTEL_EXPORTER_OTLP_METRICS_ENABLED": "false",
        "MONITORING_INSTRUMENT_REQUESTS": "false",
        "MONITORING_TRACE_MAX_CHARS": "3",
        "TRAJECTORY_ROOT_DIR": str(tmp_path),
        "TRAJECTORY_STORAGE_MODE": "single_node",
        "TRAJECTORY_READ_ENABLED": "true",
        "TRAJECTORY_CLEANUP_ENABLED": "false",
    }
    completed = subprocess.run(
        [sys.executable, "-c", code, str(local).lower(), str(remote).lower(), str(sampled).lower()],
        env=environment,
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
