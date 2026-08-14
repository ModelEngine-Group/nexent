import types
from unittest.mock import MagicMock, patch

import pytest

from backend.utils import knowledge_telemetry


def test_span_kind_distinguishes_storage_tools_from_chains():
    assert knowledge_telemetry._span_kind("knowledge.minio.fetch") == "TOOL"
    assert knowledge_telemetry._span_kind("knowledge.forward.redis_read") == "TOOL"
    assert knowledge_telemetry._span_kind("knowledge.forward.elasticsearch") == "TOOL"
    assert knowledge_telemetry._span_kind("knowledge.process") == "CHAIN"


def test_safe_attributes_maps_part_diagnostics():
    attrs = knowledge_telemetry._safe_attributes({
        "part_count": 4,
        "processor_count": 4,
        "parallel_parts": 3,
        "timeout_seconds": 300,
        "poll_interval_ms": 200,
        "queue_name": "process_part_q",
    })

    assert attrs == {
        "file.parts_count": 4,
        "processor.count": 4,
        "processor.parallel_count": 3,
        "timeout.seconds": 300,
        "poll.interval_ms": 200,
        "messaging.destination.name": "process_part_q",
    }


def _install_otel_stubs(monkeypatch):
    span = MagicMock()
    span_cm = MagicMock()
    span_cm.__enter__.return_value = span
    tracer = MagicMock()
    tracer.start_as_current_span.return_value = span_cm
    trace = MagicMock()
    trace.get_tracer.return_value = tracer
    propagate = MagicMock()
    context = MagicMock()
    status_code = MagicMock()
    status_code.OK = "OK"
    status_code.ERROR = "ERROR"
    status = MagicMock(side_effect=lambda code, description=None: (code, description))
    metrics = MagicMock()
    monkeypatch.setattr(knowledge_telemetry, "OTEL_AVAILABLE", True)
    monkeypatch.setattr(knowledge_telemetry, "trace", trace, raising=False)
    monkeypatch.setattr(knowledge_telemetry, "propagate", propagate, raising=False)
    monkeypatch.setattr(knowledge_telemetry, "otel_context", context, raising=False)
    monkeypatch.setattr(knowledge_telemetry, "Status", status, raising=False)
    monkeypatch.setattr(knowledge_telemetry, "StatusCode", status_code, raising=False)
    monkeypatch.setattr(knowledge_telemetry, "metrics", metrics, raising=False)
    monkeypatch.setattr(knowledge_telemetry, "_resource_snapshot", lambda: {})
    monkeypatch.setattr(knowledge_telemetry, "_record_metrics", MagicMock())
    return span, span_cm, trace, propagate, context, status_code


def test_knowledge_span_marks_celery_retry_without_error(monkeypatch):
    Retry = type("Retry", (Exception,), {"__module__": "celery.exceptions"})
    span, _, _, _, _, status_code = _install_otel_stubs(monkeypatch)

    with pytest.raises(Retry):
        with knowledge_telemetry.knowledge_span(
            "knowledge.forward.redis_read",
            "forward.redis_read",
            retry_attempt=2,
            retry_delay_seconds=5,
        ):
            raise Retry()

    span.record_exception.assert_not_called()
    span.set_attribute.assert_any_call("ingestion.status", "retry")
    span.set_attribute.assert_any_call("retry.attempt", 2)
    span.set_attribute.assert_any_call("retry.delay_seconds", 5.0)
    span.set_status.assert_called_with((status_code.OK, None))


def test_safe_attributes_hashes_ids_scales_bytes_and_ignores_invalid_sizes():
    attrs = knowledge_telemetry._safe_attributes({
        "task_id": "task-1",
        "tenant_id": "tenant-1",
        "index_name": "knowledge-base-1",
        "file_size_bytes": 2 * knowledge_telemetry.BYTES_PER_MB,
        "original_filename": "REPORT.PDF",
        "chunk_count": "invalid",
    })

    assert attrs["task.id"] == "task-1"
    assert attrs["tenant.id_hash"] == knowledge_telemetry._safe_hash("tenant-1")
    assert attrs["knowledge_base.id"] == knowledge_telemetry._safe_hash("knowledge-base-1")
    assert attrs["file.size_mb"] == 2.0
    assert attrs["file.extension"] == ".pdf"
    assert attrs["chunk.count"] == "invalid"


def test_inject_trace_context_degrades_when_propagation_fails(monkeypatch):
    monkeypatch.setattr(knowledge_telemetry, "OTEL_AVAILABLE", True)
    propagate = MagicMock()
    propagate.inject.side_effect = RuntimeError("collector unavailable")
    monkeypatch.setattr(knowledge_telemetry, "propagate", propagate, raising=False)

    assert knowledge_telemetry.inject_trace_context() == {}


def test_knowledge_span_records_regular_exceptions(monkeypatch):
    span, _, _, _, _, status_code = _install_otel_stubs(monkeypatch)

    with pytest.raises(ValueError, match="invalid"):
        with knowledge_telemetry.knowledge_span("knowledge.process", "process"):
            raise ValueError("invalid")

    span.record_exception.assert_called_once()
    span.set_status.assert_any_call((status_code.ERROR, "ValueError"))
    span.set_attribute.assert_any_call("error.type", "ValueError")


def test_trace_knowledge_operation_supports_sync_async_and_task_context(monkeypatch):
    captured = []

    class _Span:
        def __enter__(self):
            return None

        def __exit__(self, *args):
            return False

    def fake_span(name, stage, **attributes):
        captured.append((name, stage, attributes))
        return _Span()

    monkeypatch.setattr(knowledge_telemetry, "knowledge_span", fake_span)

    class _Task:
        request = type("Request", (), {"id": "task-7", "retries": 1})()

        @knowledge_telemetry.trace_knowledge_operation("knowledge.process", "process")
        def run(self, params):
            return params["value"]

    @knowledge_telemetry.trace_knowledge_operation("knowledge.forward", "forward")
    async def forward(params):
        return params["value"]

    assert _Task().run({"value": 3, "telemetry_context": {"traceparent": "abc"}}) == 3
    assert __import__("asyncio").run(forward({"value": 4})) == 4
    assert captured[0][2]["task_id"] == "task-7"
    assert captured[0][2]["retry_attempt"] == 2
    assert captured[0][2]["telemetry_context"] == {"traceparent": "abc"}
    assert captured[1][2]["telemetry_context"] is None


def test_set_span_attributes_only_updates_recording_span(monkeypatch):
    monkeypatch.setattr(knowledge_telemetry, "OTEL_AVAILABLE", True)
    span = MagicMock()
    span.is_recording.return_value = True
    trace = MagicMock()
    trace.get_current_span.return_value = span
    monkeypatch.setattr(knowledge_telemetry, "trace", trace, raising=False)

    knowledge_telemetry.set_span_attributes(task_id="task-1", original_filename="notes.txt")

    span.set_attributes.assert_called_once_with({"task.id": "task-1", "file.extension": ".txt"})


def test_resource_snapshot_collects_process_host_and_cgroup_metrics(monkeypatch):
    child = MagicMock()
    child.is_running.return_value = True
    child.memory_info.return_value = types.SimpleNamespace(rss=knowledge_telemetry.BYTES_PER_MB)
    process = MagicMock()
    process.children.return_value = [child]
    process.memory_info.return_value = types.SimpleNamespace(rss=2 * knowledge_telemetry.BYTES_PER_MB)
    process.cpu_percent.return_value = 12.3456
    process.num_threads.return_value = 7
    psutil = types.SimpleNamespace(
        Process=lambda: process,
        virtual_memory=lambda: types.SimpleNamespace(percent=42.1234, available=3 * knowledge_telemetry.BYTES_PER_MB),
        cpu_percent=lambda interval: 24.5678,
    )
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "psutil":
            return psutil
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    monkeypatch.setattr("builtins.open", MagicMock(side_effect=[
        MagicMock(__enter__=lambda self: self, __exit__=lambda *args: None, read=lambda: str(4 * knowledge_telemetry.BYTES_PER_MB)),
        MagicMock(__enter__=lambda self: self, __exit__=lambda *args: None, read=lambda: "max"),
    ]))

    snapshot = knowledge_telemetry._resource_snapshot()

    assert snapshot["process.rss_memory_mb"] == 2.0
    assert snapshot["process_tree.rss_memory_mb"] == 3.0
    assert snapshot["container.used_memory_mb"] == 4.0
    assert "container.memory_limit_mb" not in snapshot


def test_record_metrics_records_available_resource_measurements(monkeypatch):
    monkeypatch.setattr(knowledge_telemetry, "OTEL_AVAILABLE", True)
    histogram = MagicMock()
    meter = MagicMock()
    meter.create_histogram.return_value = histogram
    metrics = MagicMock()
    metrics.get_meter.return_value = meter
    monkeypatch.setattr(knowledge_telemetry, "metrics", metrics, raising=False)

    knowledge_telemetry._record_metrics(
        "forward",
        10.5,
        {"process.rss_memory_mb": 3.0, "process.cpu_percent": 12.0},
    )

    assert histogram.record.call_count == 3


def test_knowledge_span_degrades_when_setup_fails(monkeypatch):
    monkeypatch.setattr(knowledge_telemetry, "OTEL_AVAILABLE", True)
    trace = MagicMock()
    trace.get_tracer.side_effect = RuntimeError("tracing unavailable")
    monkeypatch.setattr(knowledge_telemetry, "trace", trace, raising=False)
    monkeypatch.setattr(knowledge_telemetry, "_resource_snapshot", lambda: {})

    with knowledge_telemetry.knowledge_span("knowledge.process", "process") as span:
        assert span is None
