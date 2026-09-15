from __future__ import annotations

import threading
from typing import Any


try:
    from opentelemetry import trace
    from opentelemetry.trace import SpanKind, Status, StatusCode

    OTEL_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    trace = None
    SpanKind = None
    Status = None
    StatusCode = None
    OTEL_AVAILABLE = False


_TRACER_NAME = "nexent.thread_manager"
_OPENINFERENCE_SPAN_KIND = "openinference.span.kind"
_OPENINFERENCE_CHAIN = "CHAIN"
_NEXENT_SPAN_KIND = "nexent.span.kind"
_NEXENT_THREAD_KIND = "thread"


def _count_attributes(counts: tuple[int, int, int, int]) -> dict[str, int]:
    return {
        "thread.counts.managed_active": counts[0],
        "thread.counts.queued": counts[1],
        "thread.counts.running": counts[2],
        "thread.counts.stuck": counts[3],
        "thread.counts.python_active_threads": threading.active_count(),
    }


def _execution_attributes(
    service_name: str,
    event: str,
    execution: Any,
    counts: tuple[int, int, int, int],
    dedicated: bool,
    fields: dict[str, Any],
) -> dict[str, Any]:
    attributes: dict[str, Any] = {
        _OPENINFERENCE_SPAN_KIND: _OPENINFERENCE_CHAIN,
        _NEXENT_SPAN_KIND: _NEXENT_THREAD_KIND,
        "thread.event": event,
        "thread.service.name": service_name,
        "thread.execution.id": execution.execution_id,
        "thread.lane": execution.lane,
        "thread.task.name": execution.spec.task_name,
        "thread.owner": execution.spec.owner,
        "thread.state": execution.state.value,
        "thread.dedicated": dedicated,
        **_count_attributes(counts),
    }
    attributes.update({f"thread.{key}": value for key, value in fields.items()})
    if execution.spec.run_id is not None:
        attributes["thread.run.id"] = execution.spec.run_id
    if execution.spec.attempt_id is not None:
        attributes["thread.attempt.id"] = execution.spec.attempt_id
    if "result" in fields and execution.started_at_monotonic is not None:
        attributes["thread.queue_wait_ms"] = max(
            0.0,
            (
                execution.started_at_monotonic
                - execution.created_at_monotonic
            )
            * 1000,
        )
        if execution.finished_at_monotonic is not None:
            attributes["thread.duration_ms"] = max(
                0.0,
                (
                    execution.finished_at_monotonic
                    - execution.started_at_monotonic
                )
                * 1000,
            )
    return attributes


class OpenTelemetryThreadTelemetry:
    """Emit an immediate statistics span after each managed state change."""

    def __init__(self) -> None:
        self._tracer = (
            trace.get_tracer(_TRACER_NAME)
            if OTEL_AVAILABLE and trace is not None
            else None
        )

    def record_snapshot(
        self,
        service_name: str,
        event: str,
        execution: Any,
        counts: tuple[int, int, int, int],
        *,
        dedicated: bool,
        **fields: Any,
    ) -> None:
        if self._tracer is None or SpanKind is None:
            return
        span = None
        try:
            attributes = _execution_attributes(
                service_name,
                event,
                execution,
                counts,
                dedicated,
                fields,
            )
            span = self._tracer.start_span(
                "thread.manager.snapshot",
                kind=SpanKind.INTERNAL,
                attributes=attributes,
            )
            result = fields.get("result")
            if result in {
                "failed",
                "timed_out",
                "stuck",
                "rejected",
                "submit_failed",
            }:
                if Status is not None and StatusCode is not None:
                    span.set_status(Status(StatusCode.ERROR, result))
        except Exception:
            return
        finally:
            if span is not None:
                try:
                    span.end()
                except Exception:
                    pass


_thread_telemetry = OpenTelemetryThreadTelemetry()


def get_thread_telemetry() -> OpenTelemetryThreadTelemetry:
    return _thread_telemetry
