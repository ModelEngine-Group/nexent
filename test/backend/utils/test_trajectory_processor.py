# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Local processor units with real spans and temporary, isolated file storage."""

import asyncio
import base64
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from google.protobuf.json_format import ParseDict
from infrastructure.observability.trajectory_otlp import span_request
from infrastructure.observability.trajectory_processor import LocalTrajectoryProcessor
from infrastructure.observability.trajectory_store import (
    CaptureIdentity,
    TrajectoryFileStore,
)
from nexent.core.concurrency import LanePolicy, ManagedThreadSpec, ThreadManager
from nexent.monitor.span_processor import MonitoringSpanProcessor
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from opentelemetry.sdk.trace import SpanLimits, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import ALWAYS_OFF, Decision
from opentelemetry.trace import Link, SpanContext, Status, StatusCode, TraceFlags


@pytest.fixture
def capture(tmp_path):
    root_id = str(uuid4())
    TrajectoryFileStore.provision(tmp_path, root_id)
    store = TrajectoryFileStore(tmp_path, root_id, authorize=lambda _: None)
    metadata = SimpleNamespace(tenant_id="tenant", user_id="user", conversation_id=123, agent_id=42, extra_metadata={})
    processor = LocalTrajectoryProcessor(store, lambda: metadata)
    manager = ThreadManager("trajectory-test", {"background-service": LanePolicy("background-service", 1, 0)})
    manager.start()
    processor.start(manager, ManagedThreadSpec("trajectory-writer", "test", close_hook=processor.request_stop))
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(processor)
    yield SimpleNamespace(
        processor=processor,
        store=store,
        provider=provider,
        tracer=provider.get_tracer("test"),
        identity=CaptureIdentity("tenant", "user", "123", "42"),
        metadata=metadata,
    )
    processor.shutdown()
    assert not processor._active and not processor._started
    provider.shutdown()
    asyncio.run(manager.shutdown(timeout=2))
    assert manager.snapshot().active_count == 0


def requests(capture):
    result = []
    for path in capture.store.root.rglob("*.otlp.jsonl"):
        result.extend(json.loads(line) for line in path.read_text().splitlines())
    return result


def bodies(capture):
    return [
        span
        for request in requests(capture)
        for resource in request["resourceSpans"]
        for scope in resource["scopeSpans"]
        for span in scope["spans"]
    ]


def attrs(span):
    return {a["key"]: next(iter(a["value"].values())) for a in span["attributes"]}


def test_parent_hierarchy_full_content_and_terminal_archive(capture):
    with capture.tracer.start_as_current_span("agent.run"):
        with capture.tracer.start_as_current_span("model", attributes={"openinference.span.kind": "LLM"}) as model:
            model.set_attributes(
                {
                    "input.value": "preview",
                    "nexent.local.input.value": "完整请求" * 5000,
                    "output.value": "回答",
                    "llm.token_count.completion": 12,
                }
            )
        with capture.tracer.start_as_current_span("tool", attributes={"openinference.span.kind": "TOOL"}) as tool:
            tool.set_attribute("output.value", "工具结果")
            tool.add_event("tool.done", {"result_size": 4})
    assert capture.processor.force_flush(2000)
    meta = capture.store.manifest(capture.identity)
    assert meta["runs"][0]["capture_state"] == "ready"
    assert meta["runs"][0]["business_status"] == "completed"
    spans = {span["name"]: span for span in bodies(capture) if span["name"] != "nexent.trajectory.fragment"}
    assert set(spans) == {"agent.run", "model", "tool"}
    assert attrs(spans["model"])["input.value"] == "完整请求" * 5000
    assert not any(key.startswith("nexent.local.") for key in attrs(spans["model"]))
    assert spans["model"]["parentSpanId"] == spans["agent.run"]["spanId"]
    assert attrs(spans["tool"])["nexent.parent_record_id"] == attrs(spans["agent.run"])["nexent.record_id"]


def test_active_snapshot_is_durable_but_not_published(capture):
    with capture.tracer.start_as_current_span("agent.run") as root:
        root.set_attribute("nexent.local.input.value", "尚在执行的输入")
        assert capture.processor.force_flush(2000)
        run = capture.store.manifest(capture.identity)["runs"][0]
        assert run["confirmed_bytes"] > 0 and run["publication_no"] is None
        fragments = [span for span in bodies(capture) if span["name"] == "nexent.trajectory.fragment"]
        assert fragments and fragments[0]["events"]
    assert capture.processor.force_flush(2000)


def test_server_message_identity_reaches_root_and_manifest(capture):
    capture.metadata.extra_metadata["trajectory_source_message_id"] = "11"
    capture.store.source_query = lambda identity, upper: ["11"]
    with capture.tracer.start_as_current_span("agent.run"):
        pass
    assert capture.processor.force_flush(2000)
    meta = capture.store.manifest(capture.identity)
    assert meta["source_message_ids"] == ["11"]
    assert meta["captured_from_start"] and not meta["has_uncaptured_history"]
    assert meta["runs"][0]["source_message_id"] == "11"
    root = next(body for body in bodies(capture) if body["name"] == "agent.run")
    assert attrs(root)["nexent.source_message_id"] == "11"


def test_local_span_duration_is_monotonic_and_does_not_change_remote_span(capture, monkeypatch):
    clock = SimpleNamespace(value=10.0)
    monkeypatch.setattr("infrastructure.observability.trajectory_processor.time.perf_counter", lambda: clock.value)
    remote = InMemorySpanExporter()
    capture.provider.add_span_processor(MonitoringSpanProcessor(SimpleSpanProcessor(remote)))
    with capture.tracer.start_as_current_span("agent.run"):
        clock.value = 10.2
        with capture.tracer.start_as_current_span("tool", attributes={"openinference.span.kind": "TOOL"}):
            clock.value = 10.5
        clock.value = 11.0
    assert capture.processor.force_flush(2000)
    spans = {body["name"]: attrs(body) for body in bodies(capture) if body["name"] != "nexent.trajectory.fragment"}
    assert spans["agent.run"]["nexent.duration_ms"] == pytest.approx(1000)
    assert spans["tool"]["nexent.duration_ms"] == pytest.approx(300)
    assert all("nexent.duration_ms" not in body.attributes for body in remote.get_finished_spans())
    assert not capture.processor._started


@pytest.mark.parametrize("elapsed", [-1.0, float("nan"), float("inf")])
def test_invalid_local_clock_keeps_completed_business_and_unknown_duration(capture, monkeypatch, elapsed):
    clock = SimpleNamespace(value=10.0)
    monkeypatch.setattr("infrastructure.observability.trajectory_processor.time.perf_counter", lambda: clock.value)
    with capture.tracer.start_as_current_span("agent.run"):
        clock.value += elapsed
    assert capture.processor.force_flush(2000)
    root = next(body for body in bodies(capture) if body["name"] == "agent.run")
    assert "nexent.duration_ms" not in attrs(root)
    assert attrs(root)["nexent.availability.duration_ms"] == "not_captured"
    assert capture.store.manifest(capture.identity)["runs"][0]["business_status"] == "completed"


@pytest.mark.parametrize("duration", [0, 7])
def test_sdk_reported_duration_takes_priority_over_local_observer(capture, monkeypatch, duration):
    clock = SimpleNamespace(value=10.0)
    monkeypatch.setattr("infrastructure.observability.trajectory_processor.time.perf_counter", lambda: clock.value)
    with capture.tracer.start_as_current_span("agent.run", attributes={"nexent.duration_ms": duration}):
        clock.value = 11.0
    assert capture.processor.force_flush(2000)
    root = next(body for body in bodies(capture) if body["name"] == "agent.run")
    assert float(attrs(root)["nexent.duration_ms"]) == duration


@pytest.mark.parametrize("prefix", ["", "nexent.local."])
def test_sdk_unavailable_duration_prevents_local_fallback(capture, monkeypatch, prefix):
    clock = SimpleNamespace(value=10.0)
    monkeypatch.setattr("infrastructure.observability.trajectory_processor.time.perf_counter", lambda: clock.value)
    with capture.tracer.start_as_current_span(
        "agent.run", attributes={f"{prefix}nexent.availability.duration_ms": "not_captured"},
    ):
        clock.value = 11.0
    assert capture.processor.force_flush(2000)
    root = next(body for body in bodies(capture) if body["name"] == "agent.run")
    assert attrs(root)["nexent.availability.duration_ms"] == "not_captured"
    assert "nexent.duration_ms" not in attrs(root)
    assert not capture.processor._started


@pytest.mark.parametrize("technical_parent", [False, True])
def test_invocation_ownership_survives_technical_spans_and_remote_projection(capture, technical_parent):
    from contextlib import nullcontext

    remote = InMemorySpanExporter()
    capture.provider.add_span_processor(MonitoringSpanProcessor(SimpleSpanProcessor(remote)))
    child_id = uuid4().hex
    grandchild_id = uuid4().hex
    with capture.tracer.start_as_current_span("agent.run") as root:
        parent_scope = (
            capture.tracer.start_as_current_span("agent.run.loop", attributes={"openinference.span.kind": "CHAIN"})
            if technical_parent else nullcontext()
        )
        with parent_scope:
            with capture.tracer.start_as_current_span("root.model", attributes={"openinference.span.kind": "LLM"}):
                pass
            with (
                capture.tracer.start_as_current_span(
                    "agent.subagent.child",
                    attributes={"openinference.span.kind": "AGENT", "subagent.invocation_id": child_id},
                ),
                capture.tracer.start_as_current_span("child.context", attributes={"openinference.span.kind": "CHAIN"}),
            ):
                with capture.tracer.start_as_current_span("child.tool", attributes={"openinference.span.kind": "TOOL"}):
                    pass
                with (
                    capture.tracer.start_as_current_span(
                        "agent.subagent.grandchild",
                        attributes={"openinference.span.kind": "AGENT", "subagent.invocation_id": grandchild_id},
                    ),
                    capture.tracer.start_as_current_span("grandchild.model", attributes={"openinference.span.kind": "LLM"}),
                ):
                    pass
            with capture.tracer.start_as_current_span("agent.subagent.sibling", attributes={"openinference.span.kind": "AGENT"}):
                pass
        root_record = root.attributes["nexent.record_id"]
    assert capture.processor.force_flush(2000)
    spans = {span["name"]: attrs(span) for span in bodies(capture) if span["name"] != "nexent.trajectory.fragment"}
    assert spans["agent.run"]["nexent.invocation_id"] == root_record
    assert "nexent.parent_invocation_id" not in spans["agent.run"]
    assert spans["root.model"]["nexent.invocation_id"] == root_record
    assert spans["agent.subagent.child"]["nexent.invocation_id"] == child_id
    assert spans["agent.subagent.child"]["nexent.parent_invocation_id"] == root_record
    assert spans["child.context"]["nexent.invocation_id"] == child_id
    assert spans["child.tool"]["nexent.invocation_id"] == child_id
    assert spans["agent.subagent.grandchild"]["nexent.invocation_id"] == grandchild_id
    assert spans["agent.subagent.grandchild"]["nexent.parent_invocation_id"] == child_id
    assert spans["grandchild.model"]["nexent.invocation_id"] == grandchild_id
    sibling = spans["agent.subagent.sibling"]
    assert sibling["nexent.invocation_id"] == sibling["nexent.record_id"]
    assert sibling["nexent.parent_invocation_id"] == root_record
    assert sibling["nexent.invocation_id"] not in {root_record, child_id}
    assert all("nexent.invocation_id" not in body.attributes for body in remote.get_finished_spans())
    assert all("nexent.parent_invocation_id" not in body.attributes for body in remote.get_finished_spans())
    remote_child = next(body for body in remote.get_finished_spans() if body.name == "agent.subagent.child")
    assert remote_child.attributes["subagent.invocation_id"] == child_id
    assert all(not any(key.startswith("nexent.local.") for key in body.attributes) for body in remote.get_finished_spans())


@pytest.mark.parametrize("business_status", ["completed", "failed", "cancelled", "interrupted"])
@pytest.mark.parametrize("serialization_failed", [False, True])
def test_root_capture_preserves_business_outcome(capture, monkeypatch, business_status, serialization_failed):
    from infrastructure.observability import trajectory_processor as module

    def fail_serialization(span, **kwargs):
        raise ValueError("Controlled invalid URL or unsupported local payload")

    if serialization_failed:
        monkeypatch.setattr(module, "span_request", fail_serialization)
    with capture.tracer.start_as_current_span("agent.run") as root:
        root.set_attribute("nexent.business_status", business_status)
        if business_status == "failed":
            root.set_status(Status(StatusCode.ERROR, "Controlled business error"))
    assert capture.processor.force_flush(2000)
    run = capture.store.manifest(capture.identity)["runs"][0]
    assert run["business_status"] == business_status
    assert run["capture_state"] == ("incomplete" if serialization_failed else "ready")
    assert not capture.processor._active and not capture.processor._started


def test_revoked_capture_releases_writer_and_seals_only_confirmed_content(capture):
    maintenance = TrajectoryFileStore(capture.store.root, capture.store.storage_root_id, authorize=lambda _: None)
    capture.processor._maintenance_store = maintenance
    with capture.tracer.start_as_current_span("agent.run") as root:
        root.set_attribute("nexent.local.input.value", "authorized-input")
        assert capture.processor.force_flush(2000)
        before = maintenance.manifest(capture.identity)["runs"][0]

        def deny(_):
            raise PermissionError("Controlled membership revocation")

        capture.store.authorize = deny
        root.set_attribute("nexent.local.output.value", "revoked-output")
        assert capture.processor.force_flush(2000)
        run = maintenance.manifest(capture.identity)["runs"][0]
        assert run["confirmed_bytes"] == before["confirmed_bytes"]
        assert run["capture_state"] == "incomplete" and run["business_status"] == "interrupted"
        assert not capture.processor._writers
        assert "revoked-output" not in json.dumps(requests(capture))
        maintenance.recover(capture.identity, run["trajectory_id"])
    assert capture.processor.force_flush(2000)
    assert not capture.processor._terminal


def test_overflow_is_explicit_incomplete_and_does_not_block_business(capture):
    capture.processor.run_queue_max_bytes = 256
    result = None
    with capture.tracer.start_as_current_span("agent.run") as root:
        root.set_attribute("output.value", "x" * 4096)
        result = "business completed"
    assert result == "business completed"
    assert capture.processor.force_flush(2000)
    run = capture.store.manifest(capture.identity)["runs"][0]
    assert run["capture_state"] == "incomplete"
    assert run["safe_error"] == "capture_gap"


def test_failed_root_retains_failed_business_status(capture):
    with capture.tracer.start_as_current_span("agent.run") as root:
        root.set_status(Status(StatusCode.ERROR, "controlled failure"))
    assert capture.processor.force_flush(2000)
    assert capture.store.manifest(capture.identity)["runs"][0]["business_status"] == "failed"


def test_dropped_event_attributes_mark_local_archive_incomplete(capture):
    with capture.tracer.start_as_current_span("agent.run") as root:
        root.add_event("observed", {f"key-{number}": number for number in range(200)})
    assert capture.processor.force_flush(2000)
    run = capture.store.manifest(capture.identity)["runs"][0]
    assert run["capture_state"] == "incomplete" and run["safe_error"] == "otel_dropped_data"
    root_body = next(span for span in bodies(capture) if span["name"] == "agent.run")
    assert root_body["events"][0]["droppedAttributesCount"] > 0


def test_otlp_json_decodes_against_official_schema(capture):
    with capture.tracer.start_as_current_span("agent.run") as root:
        root.add_event("observed", {"count": 7})
    assert capture.processor.force_flush(2000)

    def protobuf_json(value):
        if isinstance(value, list):
            return [protobuf_json(item) for item in value]
        if isinstance(value, dict):
            return {
                key: base64.b64encode(bytes.fromhex(item)).decode()
                if key in {"traceId", "spanId", "parentSpanId"}
                else protobuf_json(item)
                for key, item in value.items()
            }
        return value

    for request in requests(capture):
        decoded = ParseDict(protobuf_json(request), ExportTraceServiceRequest())
        assert decoded.resource_spans[0].scope_spans[0].spans[0].trace_id


def test_sampler_keeps_unsampled_local_records_without_setting_sampled_bit():
    sampler = LocalTrajectoryProcessor.wrap_sampler(ALWAYS_OFF)
    result = sampler.should_sample(None, 123, "agent.run")
    assert result.decision == Decision.RECORD_ONLY
    provider = TracerProvider(sampler=sampler, shutdown_on_exit=False)
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    with provider.get_tracer("test").start_as_current_span("test") as span:
        assert span.is_recording() and not span.get_span_context().trace_flags.sampled
    provider.shutdown()


def test_full_local_payload_cannot_leak_to_remote_export():
    provider = TracerProvider(shutdown_on_exit=False)
    remote = InMemorySpanExporter()
    provider.add_span_processor(MonitoringSpanProcessor(SimpleSpanProcessor(remote)))
    with provider.get_tracer("test").start_as_current_span("model") as span:
        span.set_attributes({"input.value": "preview", "nexent.local.input.value": "private full body"})
        span.add_event("preview", {"nexent.local.input.value": "private event body", "count": 1})
    exported = remote.get_finished_spans()[0]
    assert dict(exported.attributes) == {"input.value": "preview"}
    assert "private full body" not in json.dumps(span_request(exported))
    assert "private event body" not in json.dumps(span_request(exported))
    assert dict(exported.events[0].attributes) == {"count": 1}
    provider.shutdown()


def test_remote_private_filter_preserves_otel_dropped_counts():
    provider = TracerProvider(
        shutdown_on_exit=False,
        span_limits=SpanLimits(
            max_attributes=2,
            max_events=1,
            max_links=1,
            max_event_attributes=2,
            max_link_attributes=2,
        ),
    )
    remote = InMemorySpanExporter()
    provider.add_span_processor(MonitoringSpanProcessor(SimpleSpanProcessor(remote)))
    link_context = SpanContext(1, 2, False, TraceFlags.SAMPLED)
    with provider.get_tracer("test").start_as_current_span(
        "model",
        links=[
            Link(link_context),
            Link(link_context, {"discard": "x", "nexent.local.input.value": "private", "count": 7}),
        ],
    ) as span:
        span.set_attributes({"discard": "x", "nexent.local.input.value": "private", "count": 7})
        span.add_event("discard")
        span.add_event("visible", {"discard": "x", "nexent.local.output.value": "private", "count": 7})
    exported = remote.get_finished_spans()[0]
    assert exported.dropped_attributes == 1
    assert exported.dropped_events == exported.dropped_links == 1
    assert exported.events[0].dropped_attributes == exported.links[0].dropped_attributes == 1
    assert (
        dict(exported.attributes)
        == dict(exported.events[0].attributes)
        == dict(exported.links[0].attributes)
        == {"count": 7}
    )
    provider.shutdown()
