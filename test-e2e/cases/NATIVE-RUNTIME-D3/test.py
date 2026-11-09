# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Real native provider/tool exchanges over restricted local and Docker execution."""

import asyncio
import hashlib
import inspect
import json
import logging
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from threading import Event

import pytest
from nexent.core.agents.agent_model import ToolConfig
from nexent.core.agents.native_runtime import NativeModel, NativeToolCallingAgent
from nexent.core.agents.nexent_agent import (
    NexentAgent,
    _wrap_tool_with_monitoring,
    get_local_python_authorized_imports,
)
from nexent.core.agents.sandbox import (
    SandboxConfig,
    SandboxLevel,
    build_python_executor,
    release_python_executor,
)
from nexent.core.concurrency.cancellation import RunCancellationScope
from nexent.core.models.openai_llm import OpenAIModel
from nexent.core.tools.list_directory_tool import ListDirectoryTool
from nexent.core.utils.observer import MessageObserver
from nexent.monitor import AgentRunMetadata, MonitoringConfig, get_monitoring_manager
from opentelemetry import trace
from shared.case_evidence import write_case_evidence
from smolagents.local_python_executor import LocalPythonExecutor

CASE_ID = "NATIVE-RUNTIME-D3"
TASKS = {
    "direct": "Call list_directory directly on '.', then report the exact filename returned.",
    "code": "Call code_execution to print 17*19 in Python. Report the observed result.",
    "programmatic": (
        "Call code_execution and run print(list_directory(directory_path='.')) in Python. "
        "Report the filename from that actual output. Do not call list_directory directly."
    ),
    "hybrid": (
        "First call list_directory directly. Then call code_execution and run "
        "print(list_directory(directory_path='.')); print(17*19) in Python. "
        "Report the filename and computed number from those actual results."
    ),
}


@pytest.fixture(scope="module")
def observed_provider():
    settings = {
        key: os.environ[key] for key in ("MODEL_URL", "MODEL_API_KEY", "MODEL_NAME")
    }
    phoenix = os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"].rstrip("/")
    project = os.environ["PHOENIX_PROJECT_NAME"]
    request = urllib.request.Request(
        settings["MODEL_URL"].rstrip("/") + "/models",
        headers={
            "Authorization": "Bearer " + settings["MODEL_API_KEY"],
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        models = json.load(response)
    assert settings["MODEL_NAME"] in {model["id"] for model in models["data"]}
    manager = get_monitoring_manager()
    manager.configure(
        MonitoringConfig(
            enable_telemetry=True,
            otlp_endpoint=phoenix,
            otlp_traces_endpoint=phoenix + "/v1/traces",
            export_metrics=False,
            service_name="nexent-native-runtime-acceptance",
            project_name=project,
            trace_content_mode="full",
            trace_max_chars=100000,
            trace_max_items=100,
        )
    )
    try:
        yield settings, phoenix, project, manager
    finally:
        from nexent.core.agents.run_agent import shutdown_default_agent_thread_manager

        asyncio.run(shutdown_default_agent_thread_manager(timeout=10))


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D3")
@pytest.mark.parametrize("backend", ["local", "docker"])
@pytest.mark.parametrize("scenario", list(TASKS))
def test_native_execution_paths(observed_provider, tmp_path, backend, scenario):
    settings, phoenix, project, manager = observed_provider
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    marker = workspace / "native-marker.txt"
    marker.write_text("native runtime validation\n")
    observer = MessageObserver(lang="en")
    stop = Event()
    scope = RunCancellationScope(stop)
    factory = NexentAgent(observer, [], stop, agent_runtime="toolcalling")
    tool = factory.create_tool(
        ToolConfig(
            class_name="ListDirectoryTool",
            name="list_directory",
            source="local",
            description=ListDirectoryTool.description,
            inputs=json.dumps(ListDirectoryTool.inputs),
            output_type="string",
            params={"init_path": str(workspace)},
        )
    )
    tool = _wrap_tool_with_monitoring(tool, CASE_ID)
    model = OpenAIModel(
        observer=observer,
        model_id=settings["MODEL_NAME"],
        api_base=settings["MODEL_URL"],
        api_key=settings["MODEL_API_KEY"],
        max_output_tokens=2048,
        timeout_seconds=60,
        cancellation_scope=scope,
    )
    executor = None
    started = time.monotonic()
    try:
        if backend == "docker":
            config = SandboxConfig(
                level=SandboxLevel.DOCKER,
                docker_image=os.environ["NEXENT_SANDBOX_IMAGE"],
                memory_limit_mb=512,
                timeout_seconds=60,
                host_tool_timeout_seconds=30,
                failure_policy="error",
                auto_sync_outputs=False,
            )
            executor = build_python_executor(
                config,
                logging.getLogger(CASE_ID),
                host_tools_exist=True,
                cancellation_scope=scope,
            )
            assert executor._nexent_backend == "docker", (
                "Docker acceptance must not fall back to local execution"
            )
        else:
            executor = LocalPythonExecutor(
                additional_authorized_imports=get_local_python_authorized_imports()
            )
        agent = NativeToolCallingAgent(
            tools=[tool],
            model=NativeModel(model),
            executor=executor,
            observer=observer,
            max_steps=6,
            verbosity_level=0,
            instructions=(
                "Use exactly the requested execution paths. Authorized tools are prebound. "
                "Once the requested results are observed, answer immediately; do not inspect the host."
            ),
        )
        with manager.start_agent_run(
            AgentRunMetadata(agent_name=f"native-{backend}-{scenario}")
        ) as span:
            assert span is not None, "Acceptance requires actual trace collection"
            answer = str(agent.run(TASKS[scenario]))
            trace_id = format(span.get_span_context().trace_id, "032x")
            manager.set_openinference_output(answer)
        assert trace.get_tracer_provider().force_flush(), (
            "Trace export did not complete"
        )
        calls = [
            call
            for message in agent.native_messages
            for call in message.get("tool_calls", [])
        ]
        results = [
            message for message in agent.native_messages if message["role"] == "tool"
        ]
        names = [call["function"]["name"] for call in calls]
        assert set(names) <= {"list_directory", "code_execution", "final_answer"}
        assert [call["id"] for call in calls] == [
            message["tool_call_id"] for message in results
        ]
        assert len({call["id"] for call in calls}) == len(calls)
        required = {"list_directory"} if scenario == "direct" else {"code_execution"}
        if scenario == "hybrid":
            required.add("list_directory")
        assert required <= set(names)
        code_ids = {
            call["id"] for call in calls if call["function"]["name"] == "code_execution"
        }
        list_ids = {
            call["id"] for call in calls if call["function"]["name"] == "list_directory"
        }
        code_observations = [
            message["content"]
            for message in results
            if message["tool_call_id"] in code_ids
        ]
        if scenario in {"code", "hybrid"}:
            assert any(
                "323" in output and "Tool execution failed" not in output
                for output in code_observations
            )
        if scenario in {"programmatic", "hybrid"}:
            assert any(
                "native-marker.txt" in output and "Tool execution failed" not in output
                for output in code_observations
            )
        if scenario == "direct":
            assert any(
                "native-marker.txt" in message["content"]
                for message in results
                if message["tool_call_id"] in list_ids
            )
        if scenario == "programmatic":
            assert "list_directory" not in names
        if scenario in {"direct", "programmatic", "hybrid"}:
            assert "native-marker.txt" in answer
        if scenario in {"code", "hybrid"}:
            assert "323" in answer
        url = (
            phoenix
            + "/v1/projects/"
            + urllib.parse.quote(project, safe="")
            + "/spans?limit=1000"
        )
        # OTLP export completion precedes asynchronous Phoenix indexing.
        deadline = time.monotonic() + 15
        while True:
            with urllib.request.urlopen(url, timeout=30) as response:
                spans = [
                    item
                    for item in json.load(response)["data"]
                    if item["context"]["trace_id"] == trace_id
                ]
            if len([span for span in spans if span["name"] == "native.generate"]) >= 2:
                break
            assert time.monotonic() < deadline, (
                "Phoenix did not index the full native exchange"
            )
            time.sleep(0.25)
        assert not any(span["status_code"] == "ERROR" for span in spans)
        if scenario in {"programmatic", "hybrid"}:
            code_spans = {
                span["context"]["span_id"]
                for span in spans
                if span["name"] == "agent.tool.code_execution"
            }
            assert code_spans
            assert any(
                span["name"] == "agent.tool.list_directory"
                and span["parent_id"] in code_spans
                for span in spans
            )
        write_case_evidence(
            f"native-{backend}-{scenario}",
            {
                "case_id": CASE_ID,
                "scenario": scenario,
                "backend": backend,
                "trace_id": trace_id,
                "model": settings["MODEL_NAME"],
                "tool_names": names,
                "call_ids": [call["id"] for call in calls],
                "result_ids": [message["tool_call_id"] for message in results],
                "spans": [
                    {
                        "name": span["name"],
                        "span_id": span["context"]["span_id"],
                        "parent_id": span["parent_id"],
                    }
                    for span in spans
                ],
                "latency_seconds": round(time.monotonic() - started, 3),
                "runtime_sha256": hashlib.sha256(
                    Path(inspect.getfile(NativeToolCallingAgent)).read_bytes()
                ).hexdigest(),
            },
            secrets=(settings["MODEL_API_KEY"],),
        )
    finally:
        if backend == "docker" and executor is not None:
            release_python_executor(executor, logging.getLogger(CASE_ID))
        model.client.close()
        marker.unlink(missing_ok=True)


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D3")
@pytest.mark.parametrize(
    "model_id",
    ["qwen3.8-flash", "deepseek-v4.1-flash", "glm-5.3", "MiniMax-M3.1-Flash"],
)
def test_provider_native_reasoning_and_tools(observed_provider, tmp_path, model_id):
    """Provider reasoning and native tools are inspected as separate capabilities."""
    from configs.model_catalog_loader import resolve_reasoning_capability

    settings, phoenix, project, manager = observed_provider
    request = urllib.request.Request(
        settings["MODEL_URL"].rstrip("/") + "/models",
        headers={"Authorization": "Bearer " + settings["MODEL_API_KEY"]},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        assert model_id in {item["id"] for item in json.load(response)["data"]}
    capability = resolve_reasoning_capability(model_id, settings["MODEL_URL"])
    levels = (capability or {}).get("levels", [])
    effort = (
        (capability or {}).get("default")
        if model_id.startswith("deepseek")
        else ("low" if "low" in levels else (levels[0] if levels else None))
    )
    marker = tmp_path / "provider-marker.txt"
    marker.write_text("provider validation\n")
    observer = MessageObserver(lang="en")
    tool = _wrap_tool_with_monitoring(
        ListDirectoryTool(init_path=str(tmp_path), observer=observer), CASE_ID
    )
    model = OpenAIModel(
        observer=observer,
        model_id=model_id,
        api_base=settings["MODEL_URL"],
        api_key=settings["MODEL_API_KEY"],
        max_output_tokens=4096,
        timeout_seconds=90,
        reasoning_effort=effort,
        reasoning_capability=capability,
        extra_body={"thinking": {"type": "enabled"}}
        if model_id.startswith("deepseek")
        else None,
    )
    try:
        agent = NativeToolCallingAgent(
            tools=[tool], model=model, max_steps=5, verbosity_level=0
        )
        with manager.start_agent_run(
            AgentRunMetadata(agent_name="provider-" + model_id)
        ) as span:
            answer = str(
                agent.run(
                    "Call list_directory on '.' directly, then report the observed filename."
                )
            )
            trace_id = format(span.get_span_context().trace_id, "032x")
        assert "provider-marker.txt" in answer
        assert any(
            call["function"]["name"] == "list_directory"
            for message in agent.native_messages
            for call in message.get("tool_calls", [])
        )
        reasoning_present = any(
            message.get("reasoning") or message.get("reasoning_content")
            for message in agent.native_messages
        )
        # Gateway metadata is not proof of reasoning output. DeepSeek was
        # inconsistent across observed runs; its status is reported separately.
        if model_id in {"qwen3.8-flash", "glm-5.3"}:
            assert reasoning_present, (
                "Verified reasoning route produced no reasoning field"
            )
        assert trace.get_tracer_provider().force_flush()
        write_case_evidence(
            "provider-" + model_id.replace(".", "-"),
            {
                "model_id": model_id,
                "trace_id": trace_id,
                "configured_effort": effort,
                "capability_source": (capability or {}).get("source"),
                "reasoning_field_present": reasoning_present,
                "reasoning_verification": "observed"
                if reasoning_present
                else "unverified",
                "configured_thinking_object": model_id.startswith("deepseek"),
                "native_tool_observed": True,
                "answer_marker_observed": True,
            },
            secrets=(settings["MODEL_API_KEY"],),
        )
    finally:
        model.client.close()
        marker.unlink(missing_ok=True)


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D3")
def test_managed_native_child_uses_actual_python(observed_provider):
    settings, phoenix, project, manager = observed_provider
    models = [
        OpenAIModel(
            observer=MessageObserver(lang="en"),
            model_id=settings["MODEL_NAME"],
            api_base=settings["MODEL_URL"],
            api_key=settings["MODEL_API_KEY"],
            max_output_tokens=2048,
            timeout_seconds=60,
        )
        for _ in range(2)
    ]
    try:
        child = NativeToolCallingAgent(
            name="calculator",
            description="Compute using Python and report observed results.",
            tools=[],
            model=models[1],
            executor=LocalPythonExecutor(additional_authorized_imports=[]),
            max_steps=4,
            verbosity_level=0,
            instructions="Always call code_execution to print the requested arithmetic before answering.",
        )
        parent = NativeToolCallingAgent(
            tools=[],
            managed_agents=[child],
            model=models[0],
            max_steps=4,
            verbosity_level=0,
        )
        with manager.start_agent_run(
            AgentRunMetadata(agent_name="native-managed-parent")
        ) as span:
            answer = str(
                parent.run(
                    "Delegate to calculator to calculate 17*19 using Python; report the observed number."
                )
            )
            trace_id = format(span.get_span_context().trace_id, "032x")
        assert "323" in answer
        assert any(
            call["function"]["name"] == "calculator"
            for message in parent.native_messages
            for call in message.get("tool_calls", [])
        )
        assert any(
            call["function"]["name"] == "code_execution"
            for message in child.native_messages
            for call in message.get("tool_calls", [])
        )
        assert any(
            message["role"] == "tool" and "323" in message["content"]
            for message in child.native_messages
        )
        assert trace.get_tracer_provider().force_flush()
        write_case_evidence(
            "managed-native-child",
            {
                "trace_id": trace_id,
                "parent_delegated": True,
                "child_used_python": True,
                "observed_answer": 323,
            },
        )
    finally:
        for model in models:
            model.client.close()


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D3")
def test_native_mcp_tool_uses_managed_protocol_session(observed_provider):
    import sys

    from mcp import StdioServerParameters
    from nexent.core.agents.managed_mcp import ManagedMCPToolCollection
    from nexent.core.agents.run_agent import _get_default_agent_thread_manager

    settings, phoenix, project, manager = observed_provider
    observer = MessageObserver(lang="en")
    stop = Event()
    model = OpenAIModel(
        observer=observer,
        model_id=settings["MODEL_NAME"],
        api_base=settings["MODEL_URL"],
        api_key=settings["MODEL_API_KEY"],
        max_output_tokens=2048,
        timeout_seconds=60,
    )
    try:
        with ManagedMCPToolCollection(
            manager=_get_default_agent_thread_manager(),
            server_parameters=[
                StdioServerParameters(
                    command=sys.executable,
                    args=[str(Path(__file__).with_name("mcp_server.py"))],
                )
            ],
            cancellation_scope=RunCancellationScope(stop),
            tool_timeout_seconds=15,
            close_timeout_seconds=10,
        ) as collection:
            factory = NexentAgent(
                observer,
                [],
                stop,
                mcp_tool_collection=collection,
                agent_runtime="toolcalling",
            )
            tool = factory.create_tool(
                ToolConfig(class_name="nexent_echo", name="nexent_echo", source="mcp")
            )
            agent = NativeToolCallingAgent(
                tools=[tool], model=model, max_steps=4, verbosity_level=0
            )
            with manager.start_agent_run(
                AgentRunMetadata(agent_name="native-mcp-contract")
            ) as span:
                answer = str(
                    agent.run(
                        "Call nexent_echo with text NATIVE_MCP_MARKER; report the exact returned value."
                    )
                )
                trace_id = format(span.get_span_context().trace_id, "032x")
            assert "MCP_OBSERVED:NATIVE_MCP_MARKER" in answer
            assert any(
                message["role"] == "tool"
                and "MCP_OBSERVED:NATIVE_MCP_MARKER" in message["content"]
                for message in agent.native_messages
            )
            assert any(
                call["function"]["name"] == "nexent_echo"
                for message in agent.native_messages
                for call in message.get("tool_calls", [])
            )
            assert trace.get_tracer_provider().force_flush()
            write_case_evidence(
                "native-mcp-session",
                {
                    "trace_id": trace_id,
                    "native_mcp_call": True,
                    "marker_observed": True,
                    "lifecycle": "managed context owns session cleanup",
                },
            )
    finally:
        model.client.close()


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D3")
def test_real_tool_error_recovers_with_correlated_results(observed_provider, tmp_path):
    settings, phoenix, project, manager = observed_provider
    marker = tmp_path / "recovery-marker.txt"
    marker.write_text("recovery\n")
    observer = MessageObserver(lang="en")
    model = OpenAIModel(
        observer=observer,
        model_id=settings["MODEL_NAME"],
        api_base=settings["MODEL_URL"],
        api_key=settings["MODEL_API_KEY"],
        max_output_tokens=2048,
        timeout_seconds=60,
    )
    try:
        agent = NativeToolCallingAgent(
            tools=[ListDirectoryTool(init_path=str(tmp_path), observer=observer)],
            model=model,
            max_steps=5,
            verbosity_level=0,
        )
        with manager.start_agent_run(
            AgentRunMetadata(agent_name="native-error-recovery")
        ) as span:
            answer = str(
                agent.run(
                    "First call list_directory with directory_path='missing-directory'. "
                    "After observing its error, recover by calling list_directory on '.'. "
                    "Report the exact filename observed in the successful result."
                )
            )
            trace_id = format(span.get_span_context().trace_id, "032x")
        assert "recovery-marker.txt" in answer
        calls = [
            call
            for message in agent.native_messages
            for call in message.get("tool_calls", [])
            if call["function"]["name"] == "list_directory"
        ]
        assert len(calls) >= 2
        assert (
            json.loads(calls[0]["function"]["arguments"])["directory_path"]
            == "missing-directory"
        )
        results = {
            message["tool_call_id"]: message["content"]
            for message in agent.native_messages
            if message["role"] == "tool"
        }
        assert "missing-directory" in results[calls[0]["id"]]
        assert any(
            word in results[calls[0]["id"]].lower() for word in ("failed", "error")
        )
        assert "recovery-marker.txt" in results[calls[-1]["id"]]
        assert trace.get_tracer_provider().force_flush()
        write_case_evidence(
            "native-error-recovery",
            {
                "trace_id": trace_id,
                "call_ids": [call["id"] for call in calls],
                "error_observed": True,
                "recovery_observed": True,
            },
        )
    finally:
        model.client.close()
        marker.unlink(missing_ok=True)


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D3")
def test_real_max_step_limit_does_not_add_fallback_request(observed_provider, tmp_path):
    from smolagents.utils import AgentMaxStepsError

    settings, phoenix, project, manager = observed_provider
    observer = MessageObserver(lang="en")
    model = OpenAIModel(
        observer=observer,
        model_id=settings["MODEL_NAME"],
        api_base=settings["MODEL_URL"],
        api_key=settings["MODEL_API_KEY"],
        max_output_tokens=2048,
        timeout_seconds=60,
    )
    try:
        agent = NativeToolCallingAgent(
            tools=[ListDirectoryTool(init_path=str(tmp_path), observer=observer)],
            model=model,
            max_steps=1,
            verbosity_level=0,
        )
        with manager.start_agent_run(
            AgentRunMetadata(agent_name="native-max-steps")
        ) as span:
            with pytest.raises(AgentMaxStepsError):
                agent.run(
                    "Call list_directory on '.' and report the actual result after observing it."
                )
            trace_id = format(span.get_span_context().trace_id, "032x")
        assert (
            len(
                [
                    message
                    for message in agent.native_messages
                    if message["role"] == "assistant"
                ]
            )
            == 1
        )
        assert any(message["role"] == "tool" for message in agent.native_messages)
        assert trace.get_tracer_provider().force_flush()
        write_case_evidence(
            "native-max-steps",
            {
                "trace_id": trace_id,
                "maximum_steps": 1,
                "assistant_requests": 1,
                "limit_error_observed": True,
            },
        )
    finally:
        model.client.close()


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D3")
def test_real_stream_cancellation_closes_provider_resource(observed_provider):
    from concurrent.futures import ThreadPoolExecutor

    from nexent.core.concurrency.cancellation import RunTerminated

    settings, phoenix, project, manager = observed_provider
    scope = RunCancellationScope()
    first_chunk, closed = Event(), Event()
    model = OpenAIModel(
        observer=MessageObserver(lang="en"),
        model_id=settings["MODEL_NAME"],
        api_base=settings["MODEL_URL"],
        api_key=settings["MODEL_API_KEY"],
        max_output_tokens=4096,
        timeout_seconds=60,
        cancellation_scope=scope,
        concurrency_limit=1,
    )
    original_dispatch = model._dispatch_chat_completion
    dispatches = []

    class ObservedActualStream:
        def __init__(self, stream):
            self.stream = stream

        def __iter__(self):
            for chunk in self.stream:
                first_chunk.set()
                yield chunk

        def close(self):
            self.stream.close()
            closed.set()

    def observed_dispatch(**kwargs):
        dispatches.append(True)
        return ObservedActualStream(original_dispatch(**kwargs))

    model._dispatch_chat_completion = observed_dispatch
    evidence = {}

    def run():
        with manager.start_agent_run(
            AgentRunMetadata(agent_name="native-stream-cancellation")
        ) as span:
            evidence["trace_id"] = format(span.get_span_context().trace_id, "032x")
            NativeToolCallingAgent(
                tools=[], model=model, max_steps=2, verbosity_level=0
            ).run("Write a detailed explanation of prime numbers with many examples.")

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run)
            assert first_chunk.wait(30), "Real provider stream did not start"
            started = time.monotonic()
            scope.cancel()
            with pytest.raises(RunTerminated):
                future.result(timeout=15)
        assert closed.is_set()
        assert len(dispatches) == 1
        assert not scope._closers
        assert trace.get_tracer_provider().force_flush()
        write_case_evidence(
            "native-stream-cancellation",
            {
                **evidence,
                "actual_stream_started": True,
                "provider_closed": True,
                "pending_closers": 0,
                "request_count": 1,
                "termination_seconds": round(time.monotonic() - started, 3),
            },
        )
    finally:
        scope.cancel()
        model.client.close()
