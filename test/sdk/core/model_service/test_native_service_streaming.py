# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Native adapter reasoning, completion-only output, usage and attempt regressions."""

import json
from contextlib import contextmanager

import pytest
from nexent.core.agents.native_model_service import NativeServiceModel
from nexent.core.agents.native_runtime import NativeCompletionError
from nexent.core.model_service.compatibility.legacy_chat_model import LegacyChatModel
from nexent.core.model_service.contracts import AssistantMessage, ModelEvent, TokenUsage
from test_native_service_model import native_profile as native_profile  # noqa: PLC0414


class EventService:
    def __init__(self, build):
        self.build = build
        self.closed = False

    @contextmanager
    def stream(self, request, profile, **kwargs):
        try:
            yield iter(self.build(request))
        finally:
            self.closed = True


def events_for(request, message, *, streamed=True, attempt=1):
    values = []
    if streamed:
        values += [
            {
                "type": "reasoning_delta",
                "delta": "Provider <final_answer>reasoning</final_answer>",
            },
            {"type": "text_delta", "content_kind": "text", "delta": "Public answer"},
        ]
    values += [
        {
            "type": "message_completed",
            "message": message,
            "finish_reason": message.finish_reason,
        }
    ]
    return [
        ModelEvent(
            request_id=request.request_id,
            message_id=message.message_id,
            sequence=i + 1,
            attempt=attempt,
            **value,
        )
        for i, value in enumerate(values)
    ]


@pytest.mark.parametrize("streamed", [True, False])
def test_reasoning_and_public_text_are_emitted_once_separately(
    native_profile, streamed
):
    reasoning = "Provider <final_answer>reasoning</final_answer>"
    message = AssistantMessage(
        content_parts=[{"type": "text", "text": "Public answer"}],
        reasoning_parts=[{"type": "text", "text": reasoning}],
        finish_reason="stop",
        usage=TokenUsage(
            input_tokens=100,
            output_tokens=20,
            cached_input_tokens=30,
            reasoning_tokens=5,
            origin="provider",
        ),
    )
    service = EventService(
        lambda request: events_for(request, message, streamed=streamed)
    )
    delegate = LegacyChatModel(native_profile, service)
    result = NativeServiceModel(delegate).generate(
        [{"role": "user", "content": "Task"}]
    )
    events = [json.loads(value) for value in delegate.observer.message_query]
    assert (
        "".join(
            e["content"] for e in events if e["type"] == "model_output_deep_thinking"
        )
        == reasoning
    )
    assert (
        "".join(e["content"] for e in events if e["type"] == "model_output_thinking")
        == "Public answer"
    )
    assert not any(e["type"] == "final_answer" for e in events)
    assert result.raw["reasoning_parts"] == message.reasoning_parts
    assert delegate.last_cached_input_token_count == 30
    assert delegate.last_response_diagnostics["output_tokens"] == 20
    assert delegate.last_response_diagnostics["reasoning_char_count"] == len(reasoning)
    assert delegate.last_attempt_number == 1
    assert delegate.last_retry_count == 0
    assert service.closed


def test_reasoning_only_length_reports_real_output_budget_and_no_final(native_profile):
    message = AssistantMessage(
        reasoning_parts=[{"type": "text", "text": "Still planning"}],
        finish_reason="length",
        usage=TokenUsage(
            input_tokens=10, output_tokens=64, reasoning_tokens=64, origin="provider"
        ),
    )
    service = EventService(
        lambda request: [
            ModelEvent(
                request_id=request.request_id,
                message_id=message.message_id,
                sequence=1,
                type="message_completed",
                message=message,
                finish_reason=message.finish_reason,
            )
        ]
    )
    delegate = LegacyChatModel(native_profile, service)
    with pytest.raises(NativeCompletionError) as error:
        NativeServiceModel(delegate).generate(
            [{"role": "user", "content": "Task"}], max_output_tokens=64
        )
    assert error.value.finish_reason == "length"
    assert "64" in str(error.value)
    assert "reasoning" in str(error.value).lower()
    assert "output" in str(error.value).lower()
    assert delegate.last_response_diagnostics["reasoning_only_budget_exhausted"] is True
    assert delegate.last_output_token_count == 64
    assert not any(
        json.loads(e)["type"] == "final_answer" for e in delegate.observer.message_query
    )
    assert service.closed


def test_retry_resets_diagnostics_and_rolls_back_reasoning(native_profile):
    from nexent.core.model_service.contracts import ModelError

    message = AssistantMessage(
        content_parts=[{"type": "text", "text": "Public answer"}], finish_reason="stop"
    )

    def build(request):
        error = ModelError(
            category="MODEL_RATE_LIMIT_ERROR",
            scope="provider",
            retryable=True,
            will_retry=True,
            attempt=1,
            max_attempts=2,
            safe_message="Retry",
            request_id=request.request_id,
        )
        return [
            ModelEvent(
                request_id=request.request_id,
                message_id=message.message_id,
                sequence=1,
                type="reasoning_delta",
                delta="Discarded thought",
            ),
            ModelEvent(
                request_id=request.request_id,
                message_id=message.message_id,
                sequence=2,
                type="error",
                error=error,
            ),
            ModelEvent(
                request_id=request.request_id,
                message_id=message.message_id,
                sequence=1,
                attempt=2,
                type="message_completed",
                message=message,
                finish_reason="stop",
            ),
        ]

    service = EventService(build)
    delegate = LegacyChatModel(native_profile, service)
    delegate.last_cached_input_token_count = 999
    NativeServiceModel(delegate).generate([{"role": "user", "content": "Task"}])
    assert delegate.last_retry_count == 1
    assert delegate.last_attempt_number == 2
    assert delegate.last_cached_input_token_count is None
    assert delegate.last_response_diagnostics["reasoning_char_count"] == 0
    events = [json.loads(v) for v in delegate.observer.message_query]
    assert any(
        e["type"] == "model_attempt_control"
        and e.get("phase") == "rollback"
        and e.get("attempt") == 1
        for e in events
    )
    assert service.closed


def test_service_context_error_uses_existing_terminal_error_mapping(native_profile):
    from nexent.core.model_errors import ModelInvocationTerminalError
    from nexent.core.model_service.contracts import ModelError
    from nexent.core.model_service.service import ModelServiceError

    @contextmanager
    def stream(*args, **kwargs):
        raise ModelServiceError(
            ModelError(
                category="MODEL_AUTHENTICATION_ERROR",
                scope="provider",
                retryable=False,
                safe_message="Authentication failed",
                request_id="request",
            )
        )
        yield  # pragma: no cover - Make the controlled boundary a context manager.

    service = EventService(None)
    service.stream = stream
    delegate = LegacyChatModel(native_profile, service)
    with pytest.raises(ModelInvocationTerminalError):
        NativeServiceModel(delegate).generate([{"role": "user", "content": "Task"}])


def test_cancelled_reasoning_delta_is_not_emitted(native_profile):
    from nexent.core.concurrency.cancellation import RunTerminated

    message = AssistantMessage(finish_reason="stop")
    delegate = None

    def build(request):
        delegate.stop_event.set()
        yield ModelEvent(
            request_id=request.request_id,
            message_id=message.message_id,
            sequence=1,
            type="reasoning_delta",
            delta="Must not leak after cancellation",
        )

    service = EventService(build)
    delegate = LegacyChatModel(native_profile, service)
    with pytest.raises(RunTerminated):
        NativeServiceModel(delegate).generate([{"role": "user", "content": "Task"}])
    assert not any(
        json.loads(e)["type"] == "model_output_deep_thinking"
        for e in delegate.observer.message_query
    )
    assert service.closed


def test_completion_only_intermediate_text_and_tool_calls_are_preserved(native_profile):
    from nexent.core.model_service.contracts import ToolCall

    message = AssistantMessage(
        content_parts=[{"type": "text", "text": "Checking"}],
        reasoning_parts=[{"type": "text", "text": "Provider thought"}],
        finish_reason="tool_calls",
        tool_calls=[
            ToolCall(index=0, provider_call_id="call", name="echo", raw_arguments="{}")
        ],
    )
    service = EventService(
        lambda request: [
            ModelEvent(
                request_id=request.request_id,
                message_id=message.message_id,
                sequence=1,
                type="message_completed",
                message=message,
                finish_reason="tool_calls",
            )
        ]
    )
    delegate = LegacyChatModel(native_profile, service)
    result = NativeServiceModel(delegate).generate(
        [{"role": "user", "content": "Task"}],
        native_tool_schemas=[
            {
                "type": "function",
                "function": {
                    "name": "echo",
                    "description": "Echo",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )
    assert result.tool_calls[0].id == "call"
    events = [json.loads(e) for e in delegate.observer.message_query]
    assert [e["content"] for e in events if e["type"] == "model_output_thinking"] == ["Checking"]
    assert [
        e["content"] for e in events if e["type"] == "model_output_deep_thinking"
    ] == ["Provider thought"]
    assert not any(e["type"] == "final_answer" for e in events)



def test_runtime_wrapper_exposes_token_event_diagnostics(native_profile):
    delegate = LegacyChatModel(native_profile, EventService(None))
    adapter = NativeServiceModel(delegate)
    delegate.last_finish_reason = "tool_calls"
    delegate.last_prompt_cache_usage = object()
    assert adapter.last_finish_reason == "tool_calls"
    assert adapter.last_prompt_cache_usage is delegate.last_prompt_cache_usage
