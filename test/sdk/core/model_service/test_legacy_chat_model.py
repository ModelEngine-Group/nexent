# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Existing smolagents interface and observer behavior with a controlled service."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.core.model_errors import ModelErrorCode, ModelInvocationTerminalError
from nexent.core.model_service.compatibility.legacy_chat_model import LegacyChatModel
from nexent.core.model_service.contracts import AssistantMessage, ModelEvent, TokenUsage
from nexent.core.model_service.errors import normalize_model_error
from nexent.core.model_service.http_contracts import ModelTransportError
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError
from nexent.core.utils.observer import MessageObserver
from smolagents.models import ChatMessage, MessageRole


@pytest.fixture
def setup(openai_profile):
    calls = []
    state = {
        "usage": TokenUsage(input_tokens=10, output_tokens=0, total_tokens=10),
        "attempt": 2,
    }

    @contextmanager
    def stream(request, profile, **kwargs):
        calls.append((request, profile, kwargs))
        if kwargs["scope"].cancelled:
            raise RunTerminated()
        if "error" in state:
            yield iter(
                [
                    ModelEvent(
                        request_id=request.request_id,
                        message_id=request.messages[0].message_id,
                        sequence=1,
                        type="error",
                        error=state["error"].model_copy(
                            update={"request_id": request.request_id}
                        ),
                        attempt=state["attempt"],
                    )
                ]
            )
            return
        message = AssistantMessage(
            content_parts=[{"type": "text", "text": "answer"}],
            reasoning_parts=[{"type": "text", "text": "thought"}],
            finish_reason="stop",
            usage=state["usage"],
        )
        yield iter(
            [
                ModelEvent(
                    request_id=request.request_id,
                    message_id=message.message_id,
                    sequence=1,
                    attempt=state["attempt"],
                    type="reasoning_delta",
                    delta="thought",
                ),
                ModelEvent(
                    request_id=request.request_id,
                    message_id=message.message_id,
                    sequence=2,
                    attempt=state["attempt"],
                    type="text_delta",
                    delta="answer",
                ),
                ModelEvent(
                    request_id=request.request_id,
                    message_id=message.message_id,
                    sequence=3,
                    attempt=state["attempt"],
                    type="usage",
                    usage=state["usage"],
                ),
                ModelEvent(
                    request_id=request.request_id,
                    message_id=message.message_id,
                    sequence=4,
                    attempt=state["attempt"],
                    type="message_completed",
                    message=message,
                    finish_reason="stop",
                ),
            ]
        )

    observer = MessageObserver()
    model = LegacyChatModel(
        openai_profile, SimpleNamespace(stream=stream), observer=observer
    )
    return model, state, calls, observer


def test_call_returns_real_smolagents_message_with_actual_attempt_and_zero_usage(setup):
    model, _state, calls, _observer = setup
    result = model([{"role": "user", "content": "hello"}])
    assert isinstance(result, ChatMessage)
    assert result.role == MessageRole.ASSISTANT and result.content == "answer"
    assert (
        result.token_usage.input_tokens == 10 and result.token_usage.output_tokens == 0
    )
    assert result.model_attempt_number == 2 and model.last_attempt_number == 2
    assert result.raw.reasoning_parts == [{"type": "text", "text": "thought"}]
    assert calls[0][2]["scope"] is model.cancellation_scope
    assert model.last_finish_reason == "stop"


def test_code_history_roles_and_system_messages_preserve_media_and_input(setup):
    model, _state, calls, _observer = setup
    messages = [
        {"role": "system", "content": "one"},
        {"role": "system", "content": "two"},
        ChatMessage(
            role=MessageRole.TOOL_CALL,
            content=[{"type": "text", "text": "<code>x</code>"}],
        ),
        ChatMessage(
            role=MessageRole.TOOL_RESPONSE, content=[{"type": "text", "text": "result"}]
        ),
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "https://image.test"}}
            ],
        },
    ]
    model(messages)
    request = calls[0][0]
    assert request.messages[0].content_parts == [{"type": "text", "text": "one\n\ntwo"}]
    assert request.messages[1].semantic_role == "assistant"
    assert request.messages[1].content_parts == [
        {"type": "text", "text": "<code>x</code>"}
    ]
    assert request.messages[2].semantic_role == "user"
    assert request.messages[2].content_parts[-1]["type"] == "image_url"
    assert messages[0]["content"] == "one" and messages[1]["content"] == "two"
    assert messages[2].role == MessageRole.TOOL_CALL


def test_thinking_and_content_go_to_distinct_existing_observer_methods(setup, mocker):
    model, _state, _calls, observer = setup
    thought = mocker.patch.object(observer, "add_model_reasoning_content")
    content = mocker.patch.object(observer, "add_model_new_token")
    model([{"role": "user", "content": "hello"}])
    thought.assert_called_once_with("thought")
    content.assert_called_once_with("answer")


def test_stream_uses_smolagents_deltas_without_emitting_thought_as_content(setup):
    model, _state, _calls, _observer = setup
    deltas = list(model.generate_stream([{"role": "user", "content": "hello"}]))
    assert [delta.content for delta in deltas] == ["answer", None]
    assert deltas[-1].token_usage.input_tokens == 10


def test_missing_usage_remains_unknown(setup):
    model, state, _calls, _observer = setup
    state["usage"] = TokenUsage()
    result = model.generate([{"role": "user", "content": "hello"}])
    assert result.token_usage is None and model.last_input_token_count is None
    assert model.last_output_token_count is None


def test_only_declared_parameter_overrides_are_accepted_without_mutating_saved_profile(
    setup,
):
    model, _state, calls, _observer = setup
    model([{"role": "user", "content": "hello"}], enable_thinking=True)
    assert calls[0][1].parameter_values["enable_thinking"] is True
    assert model.profile.parameter_values["enable_thinking"] is False
    with pytest.raises(ParameterValidationError):
        model([{"role": "user", "content": "hello"}], unknown_parameter="value")
    assert len(calls) == 1


def test_cancel_propagates_without_mode_fallback_or_model_error(setup):
    model, _state, calls, _observer = setup
    model.cancellation_scope.cancel()
    with pytest.raises(RunTerminated):
        model([{"role": "user", "content": "hello"}])
    assert len(calls) == 1


def test_service_error_maps_to_existing_terminal_error_contract(setup):
    model, state, _calls, _observer = setup
    state["error"] = normalize_model_error(
        ModelTransportError("HTTP_TIMEOUT"),
        request_id="request",
        attempt=2,
        max_attempts=2,
    )
    with pytest.raises(ModelInvocationTerminalError) as caught:
        model([{"role": "user", "content": "hello"}])
    assert caught.value.error_code == ModelErrorCode.TIMEOUT
    assert caught.value.attempts == 2


def controls(observer):
    return [
        json.loads(message)["phase"]
        for message in observer.message_query
        if json.loads(message)["type"] == "model_attempt_control"
    ]


@pytest.mark.parametrize("accepted", [False, True])
def test_deferred_attempt_waits_for_caller_confirmation(setup, accepted):
    model, _state, calls, observer = setup
    result = model([{"role": "user", "content": "hello"}], _defer_attempt_commit=True)
    assert result.model_attempt_commit_deferred is True
    assert controls(observer) == ["begin"]
    resolve = observer.commit_model_attempt if accepted else observer.rollback_model_attempt
    resolve(result.model_attempt_id, result.model_attempt_number)
    assert controls(observer) == ["begin", "commit" if accepted else "rollback"]
    assert len(calls) == 1


@pytest.mark.parametrize("deferred", [False, True])
def test_suppressed_repair_preserves_response_but_emits_no_observer_messages(setup, deferred):
    model, _state, calls, observer = setup
    result = model(
        [{"role": "user", "content": "repair"}],
        _defer_attempt_commit=deferred, _suppress_attempt_stream=True,
    )
    assert result.content == "answer" and result.raw.reasoning_parts
    assert result.model_attempt_number == 2 and result.model_attempt_commit_deferred is False
    assert result.token_usage.input_tokens == 10 and observer.message_query == []
    assert len(calls) == 1


def test_suppressed_stream_returns_deltas_without_observer_side_effects(setup):
    model, _state, calls, observer = setup
    result = list(model.generate_stream(
        [{"role": "user", "content": "repair"}], _suppress_attempt_stream=True,
    ))
    assert result[0].content == "answer" and result[-1].token_usage.input_tokens == 10
    assert observer.message_query == [] and len(calls) == 1


@pytest.mark.parametrize("suppressed", [False, True])
def test_failed_attempt_rolls_back_only_visible_observer_stream(setup, suppressed):
    model, state, calls, observer = setup
    state["error"] = normalize_model_error(
        ModelTransportError("HTTP_TIMEOUT"), request_id="request", attempt=2, max_attempts=2,
    )
    with pytest.raises(ModelInvocationTerminalError):
        model([{"role": "user", "content": "hello"}], _suppress_attempt_stream=suppressed)
    assert controls(observer) == ([] if suppressed else ["begin", "rollback"])
    assert len(calls) == 1


def test_early_stream_close_rolls_back_unfinished_attempt(setup):
    model, _state, _calls, observer = setup
    stream = model.generate_stream([{"role": "user", "content": "hello"}])
    assert next(stream).content == "answer"
    stream.close()
    assert controls(observer) == ["begin", "rollback"]


@pytest.mark.parametrize("options", [
    {"_defer_attempt_commit": "true"}, {"_suppress_attempt_stream": 1},
])
def test_invalid_attempt_controls_fail_before_request(setup, options):
    model, _state, calls, observer = setup
    with pytest.raises(ValueError, match="booleans"):
        model([{"role": "user", "content": "hello"}], **options)
    assert calls == [] and observer.message_query == []


@pytest.mark.parametrize('enabled,policy', [(False, 'fail'), (True, 'retry')])
def test_empty_retry_control_is_not_a_model_parameter(setup, enabled, policy):
    model, _state, calls, _observer = setup
    result = model.generate([{'role': 'user', 'content': 'hello'}], _retry_empty_response=enabled)
    assert result.content == 'answer'
    assert calls[0][2]['empty_response_policy'] == policy
    assert '_retry_empty_response' not in calls[0][1].parameter_values


@pytest.mark.parametrize('value', [None, 0, 1, 'false'])
def test_empty_retry_control_requires_boolean_before_service_call(setup, value):
    model, _state, calls, _observer = setup
    with pytest.raises(ValueError, match='booleans'):
        model.generate([{'role': 'user', 'content': 'hello'}], _retry_empty_response=value)
    assert calls == []


def test_terminal_agent_error_uses_shared_http_diagnostic():
    from nexent.core.model_service.compatibility.legacy_chat_model import LegacyChatModel
    from nexent.core.model_service.http_contracts import ModelTransportError, RawHttpResponse
    error = normalize_model_error(ModelTransportError("HTTP_STATUS_ERROR", response=RawHttpResponse(400, {}, b'{"error":{"message":"top_p must be 0.95"}}')), request_id="r1")
    terminal = LegacyChatModel._terminal(error)
    assert "(400) top_p must be 0.95" in terminal.safe_message("zh")
    assert terminal.error_code == ModelErrorCode.INVALID_REQUEST
