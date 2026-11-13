# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise the actual backend bootstrap in an isolated telemetry process."""

import os
import subprocess
import sys
from pathlib import Path

from infrastructure.observability.trajectory_store import TrajectoryFileStore


def test_backend_bootstrap_writes_full_local_agent_model_tool_trace(tmp_path):
    TrajectoryFileStore.provision(tmp_path)
    root = Path(__file__).resolve().parents[3]
    code = r"""
import asyncio
import json
import socket
from contextlib import nullcontext
from unittest.mock import patch

def forbid_network(*args, **kwargs):
    raise AssertionError("Local Trace with Metrics disabled must not open outbound sockets")

socket.socket.connect = forbid_network
# PG remains a controlled external boundary for this bootstrap unit test.
from management.db.trajectory.repository import ExecutionRepository
patch.object(ExecutionRepository, "begin", return_value=1).start()
patch.object(ExecutionRepository, "initialize", side_effect=lambda _: nullcontext()).start()
patch.object(ExecutionRepository, "expire", return_value=None).start()
from infrastructure.observability.bootstrap import monitoring_manager, local_trajectory_processor
from nexent.core.concurrency import LanePolicy, ManagedThreadSpec, ThreadManager
from nexent.monitor import AgentRunMetadata

assert monitoring_manager.is_enabled
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
        with monitoring_manager.trace_llm_request("model.attempt", "test-model", **{"input.value": {"messages": [{"content": "完整请求" * 10000}]}}):
            monitoring_manager.set_openinference_output("完整模型输出" * 10000)
        with monitoring_manager.trace_tool_call("lookup", "agent", {"query": "工具输入"}):
            monitoring_manager.set_tool_output({"answer": "完整工具输出" * 10000})
        monitoring_manager.set_openinference_output("最终答案")
    assert local_trajectory_processor.force_flush(5000)
    documents = [json.loads(line) for path in local_trajectory_processor.store.root.rglob("*.otlp.jsonl") for line in path.read_text().splitlines()]
    spans = {span["name"]: span for doc in documents for resource in doc["resourceSpans"] for scope in resource["scopeSpans"] for span in scope["spans"]}
    assert {"agent.run", "model.attempt", "agent.tool.lookup"} <= set(spans)
    def attributes(span):
        return {a["key"]: next(iter(a["value"].values())) for a in span["attributes"]}
    assert "完整请求" * 10000 in attributes(spans["model.attempt"])["input.value"]
    assert attributes(spans["model.attempt"])["output.value"] == "完整模型输出" * 10000
    assert "完整工具输出" * 10000 in attributes(spans["agent.tool.lookup"])["output.value"]
    assert attributes(spans["agent.run"])["output.value"] == "最终答案"
finally:
    local_trajectory_processor.shutdown()
    monitoring_manager._tracer_provider.shutdown()
    monitoring_manager._meter_provider.shutdown()
    asyncio.run(manager.shutdown(timeout=2))
assert manager.snapshot().active_count == 0
"""
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(root / "backend"), str(root / "sdk")]),
        "ENABLE_TELEMETRY": "true",
        "MONITORING_PROVIDER": "local_file",
        "OTEL_EXPORTER_OTLP_METRICS_ENABLED": "true",
        "MONITORING_INSTRUMENT_REQUESTS": "false",
        "MONITORING_TRACE_MAX_CHARS": "3",
        "TRAJECTORY_ROOT_DIR": str(tmp_path),

        "TRAJECTORY_CLEANUP_ENABLED": "false",
    }
    completed = subprocess.run(
        [sys.executable, "-c", code],
        env=environment,
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
