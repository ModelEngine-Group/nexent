"""UT-BE-TRACE-011/012: portable W3C carriers and optional tracing."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from opentelemetry import baggage, trace
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, TraceState

from services.human_interaction import telemetry


@pytest.mark.parametrize("sampled", [False, True])
def test_ut_be_trace_011_round_trip_preserves_sampling_and_tracestate(sampled):
    parent = SpanContext(
        trace_id=11, span_id=22, is_remote=True, trace_flags=TraceFlags(int(sampled)),
        trace_state=TraceState([("vendor", "value")]),
    )
    with trace.use_span(NonRecordingSpan(parent)):
        carrier = telemetry.capture_trace_context()
    assert carrier["tracestate"] == "vendor=value"
    carrier["baggage"] = "private=must-not-restore"
    with telemetry.restore_trace_context(json.loads(json.dumps(carrier))):
        restored = trace.get_current_span().get_span_context()
        assert (restored.trace_id, restored.span_id, restored.trace_flags, restored.trace_state) == (
            parent.trace_id, parent.span_id, parent.trace_flags, parent.trace_state,
        )
        assert baggage.get_baggage("private") is None


def test_ut_be_trace_011_carrier_survives_a_fresh_process(spans):
    with spans.tracer.start_as_current_span("request") as parent:
        carrier = telemetry.capture_trace_context()
    script = '''
import importlib.util, json, sys
from opentelemetry import trace
spec = importlib.util.spec_from_file_location("hitl_telemetry", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
with module.restore_trace_context(json.loads(sys.argv[2])):
    parent = trace.get_current_span().get_span_context()
    print(json.dumps([parent.trace_id, parent.span_id]))
'''
    result = subprocess.run(
        [sys.executable, "-c", script, str(Path(telemetry.__file__)), json.dumps(carrier)],
        capture_output=True, text=True, check=True, timeout=10,
    )
    assert json.loads(result.stdout) == [parent.get_span_context().trace_id, parent.get_span_context().span_id]


def test_ut_be_trace_012_missing_otel_is_optional(monkeypatch):
    monkeypatch.setattr(telemetry, "_propagator", None)
    monkeypatch.setattr(telemetry, "otel_context", None)
    assert telemetry.capture_trace_context() == {}
    with telemetry.restore_trace_context({"traceparent": "legacy"}):
        pass


def test_ut_be_trace_012_propagator_failure_is_isolated(monkeypatch, mocker, spans):
    propagator = mocker.Mock()
    propagator.inject.side_effect = ValueError("capture failed")
    propagator.extract.side_effect = ValueError("restore failed")
    monkeypatch.setattr(telemetry, "_propagator", propagator)
    with spans.tracer.start_as_current_span("scheduler") as parent:
        assert telemetry.capture_trace_context() == {}
        with telemetry.restore_trace_context({"traceparent": "legacy"}):
            assert not trace.get_current_span().get_span_context().is_valid
        assert trace.get_current_span() is parent
