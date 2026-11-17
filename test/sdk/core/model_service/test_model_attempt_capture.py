# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Physical capture preserves safe facts without changing the remote trace contract."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from nexent.monitor.model_attempt import ModelAttemptSession
from nexent.monitor.monitoring import LLMTokenTracker
from nexent.monitor.span_processor import MonitoringSpanProcessor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from test_model_service import Sender, complete, frame
from test_model_service import setup as setup  # noqa: PLC0414 - Shared pytest fixture.


@pytest.fixture
def capture():
    provider = TracerProvider(shutdown_on_exit=False)
    local, remote = InMemorySpanExporter(), InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(local))
    provider.add_span_processor(MonitoringSpanProcessor(SimpleSpanProcessor(remote)))
    manager = SimpleNamespace(
        is_enabled=True,
        _config=SimpleNamespace(provider="local_file", export_traces=True),
        tracer=provider.get_tracer("test"),
        record_llm_metrics=Mock(),
    )
    manager.create_token_tracker = lambda model, span: LLMTokenTracker(
        manager, model, span
    )
    try:
        yield manager, local, remote
    finally:
        provider.shutdown()


def test_physical_retries_are_detached_safe_and_remote_shape_is_preserved(capture):
    manager, local, remote = capture
    with manager.tracer.start_as_current_span(
        "logical", attributes={"openinference.span.kind": "LLM"}
    ) as logical:
        session = ModelAttemptSession(manager, "model", logical, "request", 3)
        body = {
            "model": "model",
            "messages": [{"role": "user", "content": "完整输入"}],
            "api_key": "private",
        }
        session.begin(body, config={"revision": 2})
        body["messages"][0]["content"] = "changed"
        session.fail({"category": "MODEL_RATE_LIMIT", "will_retry": True})
        session.begin({"model": "model", "messages": []})
        session.complete(
            {
                "content_parts": [{"type": "text", "text": "answer"}],
                "reasoning_parts": [{"type": "text", "text": "thought"}],
                "tool_calls": [],
            }
        )
        session.end()
    attempts = [
        span for span in local.get_finished_spans() if span.name == "model.attempt"
    ]
    assert len(attempts) == 2
    first, second = [span.attributes for span in attempts]
    assert first["nexent.attempt_id"] != second["nexent.attempt_id"]
    assert second["nexent.previous_attempt_id"] == first["nexent.attempt_id"]
    assert second["nexent.retry_reason"] == "MODEL_RATE_LIMIT"
    assert json.loads(first["input.value"])["messages"][0]["content"] == "完整输入"
    assert "private" not in str(first)
    assert len(first["nexent.request_fingerprint"]) == 64
    assert "thought" in second["nexent.reasoning.value"]
    assert [span.name for span in remote.get_finished_spans()] == ["logical"]
    assert remote.get_finished_spans()[0].attributes["openinference.span.kind"] == "LLM"


@pytest.mark.parametrize("sink", ["otlp", None, Mock()])
def test_default_sink_does_not_start_local_attempts(capture, sink):
    manager, local, _ = capture
    manager._config.provider = sink
    session = ModelAttemptSession(manager, "model", None, "request", 1)
    assert session.begin({"messages": []}) is None
    session.complete({"content_parts": []})
    session.end()
    assert not local.get_finished_spans()


@pytest.mark.parametrize("elapsed", [0, 0.125, -1, float("nan"), float("inf")])
def test_attempt_duration_distinguishes_zero_from_invalid_clock(
    capture, monkeypatch, elapsed
):
    manager, local, _ = capture
    clock = SimpleNamespace(value=100.0)
    monkeypatch.setattr(
        "nexent.monitor.model_attempt.time.perf_counter", lambda: clock.value
    )
    with manager.tracer.start_as_current_span("logical") as logical:
        session = ModelAttemptSession(manager, "model", logical, "request", 1)
        session.begin({"messages": []})
        clock.value += elapsed
        session.complete({"content_parts": []})
        session.end()
    attempt = next(
        span for span in local.get_finished_spans() if span.name == "model.attempt"
    )
    if elapsed in (0, 0.125):
        assert attempt.attributes["nexent.duration_ms"] == elapsed * 1000
    else:
        assert "nexent.duration_ms" not in attempt.attributes
        assert attempt.attributes["nexent.availability.duration_ms"] == "not_captured"
    assert attempt.attributes["nexent.business_status"] == "completed"


def test_failed_serialization_is_a_gap_and_does_not_break_execution(capture):
    manager, local, _ = capture
    with manager.tracer.start_as_current_span("logical") as logical:
        session = ModelAttemptSession(manager, "model", logical, "request", 1)
        session.begin({"messages": object()})
        session.end(cancelled=True)
    attempt = local.get_finished_spans()[0]
    assert attempt.attributes["nexent.trajectory.gap"] is True
    assert attempt.attributes["nexent.business_status"] == "cancelled"
    assert "object at" not in str(attempt.attributes)


def test_raw_error_credentials_are_scrubbed_and_partial_result_survives(capture):
    from uuid import uuid4

    from nexent.core.model_service.contracts import ModelEvent
    from nexent.core.model_service.http_contracts import RawHttpResponse
    from nexent.core.model_service.sse import SSEEvent

    manager, local, _ = capture
    with manager.tracer.start_as_current_span("logical") as logical:
        session = ModelAttemptSession(manager, "model", logical, "request", 1)
        session.begin({"messages": []})
        session.frame(SSEEvent('{"choices":[{"delta":{"content":"partial"}}]}'))
        session.event(ModelEvent(type="text_delta", request_id="request", message_id=uuid4(),
                                 sequence=1, delta="partial"))
        session.raw_response(
            RawHttpResponse(
                400, {}, b'{"error":{"message":"secret-value"}}', ("secret-value",)
            )
        )
        session.fail({"category": "MODEL_PROTOCOL", "will_retry": False})
    attempt = local.get_finished_spans()[0]
    assert "secret-value" not in str(attempt.attributes)
    assert "stream" not in json.loads(attempt.attributes["nexent.raw.value"])
    assert json.loads(attempt.attributes["output.value"])["content_parts"] == [{"type": "text", "text": "partial"}]
    assert attempt.attributes["nexent.output_complete"] is False


def test_capture_budget_preserves_business_success_and_reports_missing_body(capture):
    manager, local, _ = capture
    manager._config.local_span_processor = SimpleNamespace(run_queue_max_bytes=100)
    with manager.tracer.start_as_current_span("logical") as logical:
        session = ModelAttemptSession(manager, "model", logical, "request", 1)
        session.begin({"messages": []})
        session.complete(
            {
                "content_parts": [{"type": "text", "text": "large" * 100}],
                "usage": {"input_tokens": 3, "output_tokens": 10},
            }
        )
        session.end()
    attempt = local.get_finished_spans()[0]
    assert attempt.attributes["nexent.business_status"] == "completed"
    assert attempt.attributes["nexent.trajectory.gap"] is True
    assert attempt.attributes["nexent.output_complete"] is False
    assert attempt.attributes["llm.token_count.prompt"] == 3
    assert "large" not in attempt.attributes["output.value"]


def test_remote_children_keep_public_parent_when_local_context_is_hidden(capture):
    manager, local, remote = capture
    with (
        manager.tracer.start_as_current_span("root") as root,
        manager.tracer.start_as_current_span(
            "context", attributes={"nexent.local_only": True}
        ) as context,
        manager.tracer.start_as_current_span("logical"),
    ):
        pass
    local_model = next(
        span for span in local.get_finished_spans() if span.name == "logical"
    )
    remote_model = next(
        span for span in remote.get_finished_spans() if span.name == "logical"
    )
    assert local_model.parent.span_id == context.get_span_context().span_id
    assert remote_model.parent.span_id == root.get_span_context().span_id
    assert [span.name for span in remote.get_finished_spans()] == ["logical", "root"]


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_service_retries_save_actual_requests_and_known_usage(
    capture, setup, asynchronous
):
    from nexent.core.model_service.http_contracts import (
        ModelTransportError,
        RawHttpResponse,
    )
    from nexent.core.model_service.service import ModelService

    manager, local, remote = capture
    profile, request, limiter, _ = setup
    policy = SimpleNamespace(max_attempts=2, calculate_backoff=lambda attempt: 0)
    response = complete()
    value = json.loads(response.body)
    value["usage"] = {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13}
    sender = Sender(
        [
            ModelTransportError("HTTP_ERROR", response=RawHttpResponse(429, {}, b"{}")),
            RawHttpResponse(200, {}, json.dumps(value).encode()),
        ]
    )
    # The real manager is required at this boundary; only transport I/O is controlled.
    manager.trace_llm_request = lambda *a, **kw: manager.tracer.start_as_current_span(
        "logical",
        attributes={"openinference.span.kind": "LLM"},
    )
    manager.add_span_event = Mock()
    manager.set_span_attributes = Mock()
    manager.set_openinference_output = Mock()
    service = ModelService(
        lambda _: sender, limiter=limiter, retry_policy=policy, monitoring=manager
    )
    answer = (
        await service.ainvoke(request, profile)
        if asynchronous
        else service.invoke(request, profile)
    )
    assert answer.content_parts[0]["text"] == "answer"
    attempts = [
        span for span in local.get_finished_spans() if span.name == "model.attempt"
    ]
    assert len(attempts) == len(sender.calls) == 2
    for saved, sent in zip(attempts, sender.calls):
        assert json.loads(saved.attributes["nexent.raw.value"])[
            "request"
        ] == json.loads(sent.body_bytes)
    assert attempts[0].attributes["nexent.business_status"] == "failed"
    assert attempts[1].attributes["llm.token_count.prompt"] == 9
    assert attempts[1].attributes["llm.token_count.completion"] == 4
    assert attempts[1].attributes["nexent.usage_origin"] == "provider"
    assert len(remote.get_finished_spans()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_consumer_close_saves_partial_output_and_closes_attempt(
    capture, setup, asynchronous
):
    from nexent.core.model_service.service import ModelService

    manager, local, _ = capture
    profile, request, limiter, _ = setup
    manager.trace_llm_request = lambda *a, **kw: manager.tracer.start_as_current_span(
        "logical"
    )
    manager.add_span_event = Mock()
    manager.set_span_attributes = Mock()
    manager.set_openinference_output = Mock()
    sender = Sender(
        [[frame({"reasoning_content": "保留思考"}), frame({"content": "unread"})]]
    )
    service = ModelService(lambda _: sender, limiter=limiter, monitoring=manager)
    request = request.model_copy(update={"stream": True})
    if asynchronous:
        async with service.astream(request, profile) as events:
            await anext(events)
    else:
        with service.stream(request, profile) as events:
            next(events)
    attempt = next(
        span for span in local.get_finished_spans() if span.name == "model.attempt"
    )
    assert attempt.attributes["nexent.business_status"] == "interrupted"
    assert "保留思考" in attempt.attributes["output.value"]
    assert "保留思考" in attempt.attributes["nexent.reasoning.value"]
    assert "unread" not in attempt.attributes["nexent.raw.value"]
    assert sender.closed == 1


@pytest.mark.parametrize("terminal", ["completed", "failed", "cancelled"])
@pytest.mark.parametrize("legacy", [False, True])
def test_stream_capture_saves_only_merged_output(capture, terminal, legacy):
    from uuid import uuid4

    from nexent.core.model_service.contracts import ModelEvent, ToolCallDelta
    from nexent.core.model_service.sse import SSEEvent

    manager, local, _ = capture
    with manager.tracer.start_as_current_span("logical") as logical:
        session = ModelAttemptSession(manager, "model", logical, "request", 1)
        session.begin({"messages": []})
        message_id, call_id = uuid4(), uuid4()
        for index, (thought, text, argument) in enumerate(
            [("分析", "完整", '{"城市":'), ("完成", "回答", '"北京"}')]
        ):
            session.frame(SSEEvent('{"private_frame":true}'))
            if legacy:
                session.legacy_chunk(Mock(model_dump=Mock(return_value={
                    "choices": [{"index": 0, "delta": {
                        "reasoning_content": thought, "content": text,
                        "tool_calls": [{"index": 0, "id": "call-1", "function": {
                            "name": "weather" if index == 0 else "", "arguments": argument,
                        }}],
                    }}],
                })))
            else:
                for kind, payload in (
                    ("reasoning_delta", {"delta": thought}),
                    ("text_delta", {"delta": text}),
                    ("tool_call_delta", {"tool_call_delta": ToolCallDelta(
                        local_call_id=call_id, index=0, provider_call_id="call-1",
                        name_delta="weather" if index == 0 else "", arguments_delta=argument,
                    )}),
                ):
                    session.event(ModelEvent(type=kind, request_id="request", message_id=message_id,
                                             sequence=index + 1, **payload))
            assert "output.value" not in session.span.attributes
            assert "nexent.reasoning.value" not in session.span.attributes
        if terminal == "completed":
            session.legacy_complete("完整回答", "stop")
            session.end()
        elif terminal == "failed":
            session.fail({"category": "MODEL_PROTOCOL"})
        else:
            session.end(cancelled=True)
    attempt = next(s for s in local.get_finished_spans() if s.name == "model.attempt")
    raw = json.loads(attempt.attributes["nexent.raw.value"])
    output = json.loads(attempt.attributes["output.value"])
    assert "stream" not in raw and "private_frame" not in str(raw)
    assert "deltas" not in output
    assert output["content_parts"] == [{"type": "text", "text": "完整回答"}]
    assert output["reasoning_parts"] == [{"type": "text", "text": "分析完成"}]
    assert output["tool_calls"][0]["parsed_arguments"] == {"城市": "北京"}
    assert output["tool_calls"][0]["name"] == "weather"
    assert output["complete"] is (terminal == "completed")
    assert attempt.attributes["nexent.business_status"] == terminal


def test_stream_buffer_budget_is_reused_for_final_output(capture):
    from uuid import uuid4

    from nexent.core.model_service.contracts import ModelEvent

    manager, local, _ = capture
    manager._config.local_span_processor = SimpleNamespace(run_queue_max_bytes=2048)
    with manager.tracer.start_as_current_span("logical") as logical:
        session = ModelAttemptSession(manager, "model", logical, "request", 1)
        session.begin({"messages": []})
        for index in range(1000):
            session.event(ModelEvent(type="text_delta", request_id="request", message_id=uuid4(),
                                     sequence=index + 1, delta="a"))
        session.complete({"content_parts": [{"type": "text", "text": "a" * 1000}]})
        session.end()
    attempt = next(s for s in local.get_finished_spans() if s.name == "model.attempt")
    assert attempt.attributes["nexent.output_complete"] is True
    assert "nexent.trajectory.gap" not in attempt.attributes
    assert json.loads(attempt.attributes["output.value"])["content_parts"][0]["text"] == "a" * 1000


def test_partial_output_scrubs_credentials_split_across_chunks(capture):
    from uuid import uuid4

    from nexent.core.model_service.contracts import ModelEvent
    from nexent.core.model_service.sse import SSEEvent

    manager, local, _ = capture
    with manager.tracer.start_as_current_span("logical") as logical:
        session = ModelAttemptSession(manager, "model", logical, "request", 1)
        session.begin({"messages": []})
        session.frame(SSEEvent("ignored", sensitive_values=("private-credential",)))
        for index, text in enumerate(["private-", "credential"]):
            session.event(ModelEvent(type="text_delta", request_id="request", message_id=uuid4(),
                                     sequence=index + 1, delta=text))
        session.end(cancelled=True)
    attempt = next(s for s in local.get_finished_spans() if s.name == "model.attempt")
    assert "private-credential" not in str(attempt.attributes)
    assert "[redacted]" in attempt.attributes["output.value"]



def test_local_stream_keeps_metrics_without_per_chunk_events(capture):
    manager, local, _ = capture
    with manager.tracer.start_as_current_span("logical") as logical:
        session = ModelAttemptSession(manager, "model", logical, "request", 1)
        tracker = session.begin({"messages": []})
        for _ in range(200):
            tracker.record_token("a")
        session.complete({"content_parts": [{"type": "text", "text": "a" * 200}],
                          "usage": {"input_tokens": 3, "output_tokens": 50},
                          "provider_metadata": {"model": "model", "unmapped_delta_fields": [{"x": "delta"}]}})
        session.end()
    attempt = next(s for s in local.get_finished_spans() if s.name == "model.attempt")
    assert not attempt.dropped_events
    assert [event.name for event in attempt.events] == ["model.requested", "first_token_received", "model.finished"]
    assert attempt.attributes["llm.token_count.completion"] == 50
    assert attempt.attributes["llm.ttft_ms"] >= 0
    output = json.loads(attempt.attributes["output.value"])
    assert output["provider_metadata"] == {"model": "model"}


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_service_stream_preserves_deltas_but_archives_final_message(capture, setup, asynchronous):
    from nexent.core.model_service.service import ModelService
    from nexent.core.model_service.sse import SSEEvent

    manager, local, _ = capture
    profile, request, limiter, _ = setup
    manager.trace_llm_request = lambda *a, **kw: manager.tracer.start_as_current_span("logical")
    manager.add_span_event = Mock()
    manager.set_span_attributes = Mock()
    manager.set_openinference_output = Mock()
    sender = Sender([[frame({"reasoning_content": "分析"}), frame({"reasoning_content": "完成"}),
                      frame({"content": "完整"}), frame({"content": "回答"}),
                      frame(finish="stop"), SSEEvent("[DONE]")]])
    service = ModelService(lambda _: sender, limiter=limiter, monitoring=manager)
    request = request.model_copy(update={"stream": True})
    if asynchronous:
        async with service.astream(request, profile) as events:
            received = [event async for event in events]
    else:
        with service.stream(request, profile) as events:
            received = list(events)
    assert [event.delta for event in received if event.type == "text_delta"] == ["完整", "回答"]
    assert [event.delta for event in received if event.type == "reasoning_delta"] == ["分析", "完成"]
    assert len(sender.calls) == sender.closed == 1
    attempt = next(s for s in local.get_finished_spans() if s.name == "model.attempt")
    output = json.loads(attempt.attributes["output.value"])
    assert output["complete"] is True and "deltas" not in output
    assert output["content_parts"] == [{"type": "text", "text": "完整回答"}]
    assert output["reasoning_parts"] == [{"type": "text", "text": "分析完成"}]
    assert "stream" not in json.loads(attempt.attributes["nexent.raw.value"])
    assert attempt.attributes["llm.ttft_ms"] >= 0
