# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Main Agent trace naming survives early export and request/task boundaries."""

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.context import Context
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from nexent.core.concurrency import ManagedTaskSpec
from nexent.monitor import AgentRunMetadata, agent_monitoring_context, monitoring

from .conftest import assert_child, by_name


NAME_KEY = "langfuse.trace.name"


@pytest.fixture
def batch_spans(mocker):
    exporter = InMemorySpanExporter()
    mocker.patch.object(monitoring, "OTLPSpanExporterHTTP", return_value=exporter)
    mocker.patch.object(monitoring.trace, "set_tracer_provider")
    mocker.patch.object(monitoring.metrics, "set_meter_provider")
    manager = object.__new__(monitoring.MonitoringManager)
    manager.__init__()
    manager.configure(monitoring.MonitoringConfig(enable_telemetry=True, export_metrics=False))
    provider = manager._tracer_provider
    manager._tracer = provider.get_tracer("nexent-backend")
    yield SimpleNamespace(manager=manager, provider=provider, exporter=exporter, tracer=provider.get_tracer("names"))
    provider.shutdown()
    manager._meter_provider.shutdown()


@pytest.mark.parametrize("fails", [False, True])
def test_first_batch_and_http_ancestor_already_have_main_name(batch_spans, fails):
    manager = batch_spans.manager
    with batch_spans.tracer.start_as_current_span("POST /agent/run", kind=SpanKind.SERVER):
        with batch_spans.tracer.start_as_current_span("request.prepare"):
            expected = pytest.raises(RuntimeError, match="run failed") if fails else nullcontext()
            with expected, manager.start_agent_run(AgentRunMetadata(agent_name="medical", agent_display_name="麻醉助手")):
                with agent_monitoring_context(AgentRunMetadata(agent_name="child", agent_display_name="子助手")):
                    with manager.trace_llm_request("model.generate", "controlled-model"):
                        pass
                    with batch_spans.tracer.start_as_current_span("native.tool", attributes={NAME_KEY: "子助手"}):
                        pass
                assert batch_spans.provider.force_flush(timeout_millis=1000)
                first_batch = batch_spans.exporter.get_finished_spans()
                assert {s.name for s in first_batch} == {"model.generate", "native.tool"}
                assert all(s.attributes.get(NAME_KEY) == "麻醉助手" for s in first_batch)
                if fails:
                    raise RuntimeError("run failed")
        with batch_spans.tracer.start_as_current_span("request.cleanup"):
            pass
    assert batch_spans.provider.force_flush(timeout_millis=1000)
    tree = {s.name: s for s in batch_spans.exporter.get_finished_spans()}
    assert all(s.attributes.get(NAME_KEY) == "麻醉助手" for s in tree.values())
    assert_child(tree["request.prepare"], tree["POST /agent/run"])
    assert_child(tree["agent.run"], tree["request.prepare"])
    assert_child(tree["model.generate"], tree["agent.run"])
    assert_child(tree["request.cleanup"], tree["POST /agent/run"])
    assert tree["agent.run"].status.is_ok == (not fails)
    assert tree["model.generate"].attributes["agent.name"] == "child"


def test_managed_worker_names_http_ancestor_and_nested_worker(spans, threads):
    def model():
        with spans.tracer.start_as_current_span("model.generate"):
            pass

    def run():
        with spans.manager.start_agent_run(AgentRunMetadata(agent_name="medical", agent_display_name="麻醉助手")):
            execution = threads.submit("model-tool-io", ManagedTaskSpec("model", "name-test"), model)
            execution.future.result(timeout=2)

    with spans.tracer.start_as_current_span("POST /agent/run", kind=SpanKind.SERVER):
        with spans.tracer.start_as_current_span("request.prepare"):
            execution = threads.submit("agent-run", ManagedTaskSpec("run", "name-test"), run)
            execution.future.result(timeout=2)
    tree = by_name(spans)
    assert all(s.attributes.get(NAME_KEY) == "麻醉助手" for s in tree.values())
    assert_child(tree["model.generate"], tree["agent.run"])
    assert_child(tree["agent.run"], tree["request.prepare"])
    assert_child(tree["request.prepare"], tree["POST /agent/run"])


def test_sequential_main_runs_keep_one_trace_owner_and_their_own_identities(spans):
    with spans.tracer.start_as_current_span("request", kind=SpanKind.SERVER):
        for index in (1, 2):
            metadata = AgentRunMetadata(agent_name=f"agent-{index}", agent_display_name=f"助手{index}")
            with spans.manager.start_agent_run(metadata, operation_name=f"run.{index}"):
                with spans.tracer.start_as_current_span(f"model.{index}"):
                    pass
        with spans.tracer.start_as_current_span("cleanup"):
            pass
    tree = by_name(spans)
    assert all(s.attributes.get(NAME_KEY) == "助手1" for s in tree.values())
    for index in (1, 2):
        assert tree[f"run.{index}"].attributes["agent.name"] == f"agent-{index}"
        assert tree[f"run.{index}"].attributes["agent.display_name"] == f"助手{index}"
        assert_child(tree[f"run.{index}"], tree["request"])
        assert_child(tree[f"model.{index}"], tree[f"run.{index}"])


def test_real_fastapi_requests_and_worker_batches_keep_names_isolated(batch_spans, threads):
    app = FastAPI()

    @app.post("/agent/run")
    async def run(name: str):
        def worker():
            with batch_spans.manager.start_agent_run(AgentRunMetadata(agent_name="medical", agent_display_name=name)):
                with batch_spans.manager.trace_llm_request("model.generate", "controlled-model"):
                    pass
                assert batch_spans.provider.force_flush(timeout_millis=1000)
            return {"result": "done"}

        with batch_spans.tracer.start_as_current_span("request.prepare"):
            execution = threads.submit("agent-run", ManagedTaskSpec("run", "name-test"), worker)
            return execution.future.result(timeout=2)

    FastAPIInstrumentor.instrument_app(
        app, tracer_provider=batch_spans.provider, meter_provider=batch_spans.manager._meter_provider,
        exclude_spans=["receive", "send"],
    )
    try:
        with TestClient(app) as client:
            for name in ("助手甲", "助手乙"):
                response = client.post("/agent/run", params={"name": name})
                assert response.status_code == 200
                assert response.json() == {"result": "done"}
        assert batch_spans.provider.force_flush(timeout_millis=1000)
        exported = batch_spans.exporter.get_finished_spans()
        assert {s.attributes.get(NAME_KEY) for s in exported} == {"助手甲", "助手乙"}
        for name in ("助手甲", "助手乙"):
            tree = {s.name: s for s in exported if s.attributes.get(NAME_KEY) == name}
            assert set(tree) == {"POST /agent/run", "request.prepare", "agent.run", "model.generate"}
            assert_child(tree["request.prepare"], tree["POST /agent/run"])
            assert_child(tree["agent.run"], tree["request.prepare"])
            assert_child(tree["model.generate"], tree["agent.run"])
    finally:
        FastAPIInstrumentor.uninstrument_app(app)


@pytest.mark.parametrize("fails", [False, True])
def test_detached_trace_and_next_run_do_not_inherit_a_name(spans, fails):
    with spans.tracer.start_as_current_span("request", kind=SpanKind.SERVER):
        expected = pytest.raises(RuntimeError, match="failed") if fails else nullcontext()
        metadata = AgentRunMetadata(agent_name="medical", agent_display_name="麻醉助手")
        with expected, spans.manager.start_agent_run(metadata):
            with spans.tracer.start_as_current_span("detached", context=Context()):
                pass
            with spans.tracer.start_as_current_span("child"):
                pass
            if fails:
                raise RuntimeError("failed")
    with spans.tracer.start_as_current_span("next.request", kind=SpanKind.SERVER):
        with spans.manager.start_agent_run():
            with spans.tracer.start_as_current_span("next.child"):
                pass
    tree = by_name(spans)
    assert tree["request"].attributes[NAME_KEY] == tree["child"].attributes[NAME_KEY] == "麻醉助手"
    for name in ("detached", "next.request", "next.child", "agent.run"):
        assert NAME_KEY not in tree[name].attributes
    assert tree["detached"].context.trace_id != tree["request"].context.trace_id


@pytest.mark.asyncio
async def test_interleaved_requests_keep_main_names_and_child_identities(spans):
    ready = 0
    together = asyncio.Event()

    async def run(index):
        nonlocal ready
        with spans.tracer.start_as_current_span(f"http.{index}", kind=SpanKind.SERVER):
            metadata = AgentRunMetadata(agent_name=f"root.{index}", agent_display_name=f"助手{index}")
            with spans.manager.start_agent_run(metadata):
                ready += 1
                if ready == 2:
                    together.set()
                await asyncio.wait_for(together.wait(), timeout=2)
                with spans.tracer.start_as_current_span(f"model.{index}"):
                    await asyncio.sleep(0)
            with spans.tracer.start_as_current_span(f"cleanup.{index}"):
                pass

    await asyncio.gather(run(1), run(2))
    tree = by_name(spans)
    for index in (1, 2):
        for operation in ("http", "model", "cleanup"):
            assert tree[f"{operation}.{index}"].attributes.get(NAME_KEY) == f"助手{index}"
        assert_child(tree[f"cleanup.{index}"], tree[f"http.{index}"])
    assert tree["http.1"].context.trace_id != tree["http.2"].context.trace_id
