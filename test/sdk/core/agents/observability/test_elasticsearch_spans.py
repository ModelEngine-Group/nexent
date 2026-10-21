# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Omit noisy Elasticsearch spans without changing calls or business tracing."""

from types import SimpleNamespace

import pytest
from elastic_transport import (
    ApiResponseMeta,
    HttpHeaders,
    NodeConfig,
    TransportApiResponse,
)
from elasticsearch import _otel
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from nexent.monitor import monitoring
from nexent.vector_database.elasticsearch_core import ElasticSearchCore


@pytest.fixture
def telemetry(mocker, monkeypatch):
    exporter = InMemorySpanExporter()
    mocker.patch.object(monitoring, "OTLPSpanExporterHTTP", return_value=exporter)
    mocker.patch.object(monitoring.trace, "set_tracer_provider")
    mocker.patch.object(monitoring.metrics, "set_meter_provider")
    manager = object.__new__(monitoring.MonitoringManager)
    manager.__init__()
    manager.configure(monitoring.MonitoringConfig(enable_telemetry=True, export_metrics=False))
    provider = manager._tracer_provider
    monkeypatch.setattr(_otel, "_tracer", provider.get_tracer("elasticsearch-api"))
    yield SimpleNamespace(provider=provider, exporter=exporter, tracer=provider.get_tracer("test"))
    provider.shutdown()
    manager._meter_provider.shutdown()


@pytest.mark.parametrize("fails", [False, True])
def test_ut_sdk_trace_022_alias_lookup_is_not_exported(telemetry, mocker, fails):
    client = ElasticSearchCore("http://elasticsearch.invalid:9200", api_key=None)
    meta = ApiResponseMeta(
        status=200, http_version="1.1", headers=HttpHeaders({"x-elastic-product": "Elasticsearch"}),
        duration=0.01, node=NodeConfig("http", "elasticsearch.invalid", 9200),
    )
    response = TransportApiResponse(meta, {"documents": {}, ".system": {}})
    transport = mocker.patch.object(client.client.transport, "perform_request", side_effect=[
        RuntimeError("unavailable") if fails else response, TransportApiResponse(meta, None),
        TransportApiResponse(meta, {}),
    ])
    try:
        with telemetry.tracer.start_as_current_span("agent.run"):
            assert client.get_user_indices("documents*") == ([] if fails else ["documents"])
            assert client.check_index_exists("documents")
            client.client.indices.refresh(index="documents")
        assert transport.call_count == 3
        assert transport.call_args_list[0].args[:2] == ("GET", "/documents*/_alias")
        assert telemetry.provider.force_flush(timeout_millis=1000)
        spans = {s.name: s for s in telemetry.exporter.get_finished_spans()}
        assert set(spans) == {"agent.run", "indices.refresh"}
        assert spans["indices.refresh"].parent.span_id == spans["agent.run"].context.span_id
    finally:
        client.client.close()


@pytest.mark.parametrize("attributes", [
    {}, {"db.system": "postgresql", "db.operation": "indices.get_alias"},
    {"db.system": "elasticsearch", "db.operation": "msearch"},
])
def test_ut_sdk_trace_022_other_operations_are_retained(telemetry, attributes):
    with telemetry.tracer.start_as_current_span("indices.get_alias", attributes=attributes):
        pass
    assert telemetry.provider.force_flush(timeout_millis=1000)
    assert len(telemetry.exporter.get_finished_spans()) == 1


@pytest.mark.parametrize("operation,path", [
    ("search", "/documents/_search"),
    ("indices.stats", "/documents/_stats"),
    ("indices.get_settings", "/documents/_settings"),
    ("bulk", "/documents/_bulk"),
    ("indices.exists", "/documents"),
    ("indices.delete", "/documents"),
])
@pytest.mark.parametrize("fails", [False, True])
def test_noisy_elasticsearch_operations_execute_without_export(telemetry, mocker, operation, path, fails):
    client = ElasticSearchCore("http://elasticsearch.invalid:9200", api_key=None)
    meta = ApiResponseMeta(
        status=200, http_version="1.1", headers=HttpHeaders({"x-elastic-product": "Elasticsearch"}),
        duration=0.01, node=NodeConfig("http", "elasticsearch.invalid", 9200),
    )
    body = {"documents": {"value": "preserved"}}
    transport = mocker.patch.object(
        client.client.transport, "perform_request",
        side_effect=RuntimeError("unavailable") if fails else None,
        return_value=TransportApiResponse(meta, body),
    )
    target = client.client.indices if operation.startswith("indices.") else client.client
    request = getattr(target, operation.rsplit(".", 1)[-1])
    request_kwargs = {"index": "documents"}
    if operation == "bulk":
        request_kwargs["operations"] = [{"index": {"_id": "1"}}, {"text": "test"}]
    try:
        with telemetry.tracer.start_as_current_span("agent.run"):
            if fails:
                with pytest.raises(RuntimeError, match="unavailable"):
                    request(**request_kwargs)
            else:
                result = request(**request_kwargs)
                assert result.body == (True if operation == "indices.exists" else body)
            with telemetry.tracer.start_as_current_span("agent.tool.search", attributes={"tool.name": "search"}):
                pass
            with telemetry.tracer.start_as_current_span("model.generate"):
                pass
        transport.assert_called_once()
        assert transport.call_args.args[1] == path
        assert telemetry.provider.force_flush(timeout_millis=1000)
        spans = {span.name: span for span in telemetry.exporter.get_finished_spans()}
        assert set(spans) == {"agent.run", "agent.tool.search", "model.generate"}
        for name in ("agent.tool.search", "model.generate"):
            assert spans[name].parent.span_id == spans["agent.run"].context.span_id
    finally:
        client.client.close()


@pytest.mark.parametrize("operation", [
    "search", "indices.stats", "indices.get_settings", "indices.get_alias", "bulk", "indices.exists", "indices.delete",
])
@pytest.mark.parametrize("database", [None, "postgresql"])
def test_filtered_names_from_other_sources_remain_exported(telemetry, operation, database):
    attributes = {"db.operation": operation}
    if database:
        attributes["db.system"] = database
    with telemetry.tracer.start_as_current_span(operation, attributes=attributes):
        pass
    assert telemetry.provider.force_flush(timeout_millis=1000)
    span, = telemetry.exporter.get_finished_spans()
    assert span.name == operation


@pytest.mark.parametrize("operation", [
    "knowledge.process", "knowledge.minio.upload", "knowledge.process.submit.extra", "knowledge.upload.batch.extra",
])
def test_other_knowledge_spans_remain_exported(telemetry, operation):
    with telemetry.tracer.start_as_current_span(operation, attributes={"ingestion.stage": "test"}):
        pass
    assert telemetry.provider.force_flush(timeout_millis=1000)
    span, = telemetry.exporter.get_finished_spans()
    assert span.name == operation


def test_ut_sdk_trace_022_processor_preserves_lifecycle(mocker):
    from nexent.monitor.span_processor import MonitoringSpanProcessor

    delegate = mocker.Mock()
    delegate.force_flush.return_value = True
    processor = MonitoringSpanProcessor(delegate)
    span = mocker.Mock(attributes={})
    context = mocker.sentinel.context
    processor.on_start(span, parent_context=context)
    processor.on_end(span)
    assert processor.force_flush(timeout_millis=42)
    processor.shutdown()
    delegate.on_start.assert_called_once_with(span, parent_context=context)
    delegate.on_end.assert_called_once_with(span)
    delegate.force_flush.assert_called_once_with(timeout_millis=42)
    delegate.shutdown.assert_called_once_with()
