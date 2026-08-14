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


def test_knowledge_span_marks_celery_retry_without_error():
    Retry = type("Retry", (Exception,), {"__module__": "celery.exceptions"})
    span = MagicMock()
    span_cm = MagicMock()
    span_cm.__enter__.return_value = span

    with (
        patch.object(knowledge_telemetry, "OTEL_AVAILABLE", True),
        patch.object(knowledge_telemetry.trace, "get_tracer") as get_tracer,
        patch.object(knowledge_telemetry, "_resource_snapshot", return_value={}),
        patch.object(knowledge_telemetry, "_record_metrics"),
    ):
        get_tracer.return_value.start_as_current_span.return_value = span_cm
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
    span.set_status.assert_called_with(
        knowledge_telemetry.Status(knowledge_telemetry.StatusCode.OK)
    )
