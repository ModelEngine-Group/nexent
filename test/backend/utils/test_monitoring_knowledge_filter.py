# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Preserve knowledge execution while filtering selected reports at export."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from infrastructure.observability import knowledge
from nexent.monitor.span_processor import MonitoringSpanProcessor


@pytest.fixture
def pipeline(mocker):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(MonitoringSpanProcessor(SimpleSpanProcessor(exporter)))
    tracer = provider.get_tracer("nexent.knowledge_ingestion")
    mocker.patch.object(knowledge.trace, "get_tracer", return_value=tracer)
    mocker.patch.object(knowledge, "_resource_snapshot", return_value={})
    metrics = mocker.patch.object(knowledge, "_record_metrics")
    yield SimpleNamespace(provider=provider, exporter=exporter, tracer=tracer, metrics=metrics)
    provider.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["knowledge.process.submit", "knowledge.upload.batch"])
@pytest.mark.parametrize("is_async", [False, True])
@pytest.mark.parametrize("with_parent", [False, True])
@pytest.mark.parametrize("fails", [False, True])
async def test_knowledge_reports_are_filtered_without_changing_execution(
    pipeline, operation, is_async, with_parent, fails,
):
    calls = []
    result = object()

    def body():
        calls.append("executed")
        if fails:
            raise RuntimeError("business failure")
        return result

    async def async_body():
        return body()

    execute = knowledge.trace_knowledge_operation(operation, "test")(async_body if is_async else body)
    parent_scope = pipeline.tracer.start_as_current_span("agent.run") if with_parent else nullcontext()
    with parent_scope:
        expected = pytest.raises(RuntimeError, match="business failure") if fails else nullcontext()
        with expected:
            actual = await execute() if is_async else execute()
            assert actual is result
        with pipeline.tracer.start_as_current_span("knowledge.process"):
            pass

    assert calls == ["executed"]
    pipeline.metrics.assert_called_once()
    assert pipeline.provider.force_flush(timeout_millis=1000)
    spans = {span.name: span for span in pipeline.exporter.get_finished_spans()}
    assert set(spans) == ({"knowledge.process", "agent.run"} if with_parent else {"knowledge.process"})
    if with_parent:
        assert spans["knowledge.process"].parent.span_id == spans["agent.run"].context.span_id
    else:
        assert spans["knowledge.process"].parent is None
