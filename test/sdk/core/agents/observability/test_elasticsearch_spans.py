"""UT-SDK-TRACE-022: omit alias discovery spans without changing ES calls."""

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
    ])
    try:
        with telemetry.tracer.start_as_current_span("agent.run"):
            assert client.get_user_indices("documents*") == ([] if fails else ["documents"])
            assert client.check_index_exists("documents")
        assert transport.call_count == 2
        assert transport.call_args_list[0].args[:2] == ("GET", "/documents*/_alias")
        assert telemetry.provider.force_flush(timeout_millis=1000)
        spans = {s.name: s for s in telemetry.exporter.get_finished_spans()}
        assert set(spans) == {"agent.run", "indices.exists"}
        assert spans["indices.exists"].parent.span_id == spans["agent.run"].context.span_id
    finally:
        client.client.close()


@pytest.mark.parametrize("attributes", [
    {}, {"db.system": "postgresql", "db.operation": "indices.get_alias"},
    {"db.system": "elasticsearch", "db.operation": "search"},
])
def test_ut_sdk_trace_022_other_operations_are_retained(telemetry, attributes):
    with telemetry.tracer.start_as_current_span("indices.get_alias", attributes=attributes):
        pass
    assert telemetry.provider.force_flush(timeout_millis=1000)
    assert len(telemetry.exporter.get_finished_spans()) == 1


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
