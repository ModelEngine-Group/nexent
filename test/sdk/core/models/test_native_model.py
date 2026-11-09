# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Native adapter request, streaming, cancellation and resource contracts."""

from types import SimpleNamespace

import pytest
from nexent.core.agents.native_runtime import NativeModel
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.core.models.openai_llm import OpenAIModel
from nexent.core.models.retry import (
    ModelErrorCode,
    ModelInvocationTerminalError,
    ModelRetryConfig,
)
from nexent.core.utils.observer import MessageObserver


class ProviderStream:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = 0

    def __iter__(self):
        return iter(self.chunks)

    def close(self):
        self.closed += 1


@pytest.fixture
def configured_model():
    model = OpenAIModel(
        observer=MessageObserver(lang="en"),
        model_id="native-test",
        api_base="https://example.invalid/v1",
        api_key="unit-test-placeholder",
        max_output_tokens=32,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        concurrency_limit=1,
        concurrency_key=("test", "native", "model"),
        concurrency_wait_timeout_seconds=0.01,
    )
    yield model
    model.client.close()


def test_ac003_adapter_preserves_wire_history_and_releases_permit(
    configured_model, mocker
):
    delta = SimpleNamespace(content="Answer", tool_calls=None)
    stream = ProviderStream(
        [
            SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason="stop")], usage=None),
            SimpleNamespace(
                choices=[], usage=SimpleNamespace(prompt_tokens=4, completion_tokens=2)
            ),
        ]
    )
    dispatch = mocker.patch.object(
        configured_model, "_dispatch_chat_completion", return_value=stream
    )
    adapter = NativeModel(configured_model)
    history = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-a",
                    "type": "function",
                    "function": {"name": "echo", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call-a", "content": "Observed"},
    ]
    for _ in range(2):
        message = adapter.generate(history)
        assert message.content == "Answer"
        assert message.token_usage.input_tokens == 4
    request = dispatch.call_args.kwargs
    assert request["messages"] == history
    assert request["max_tokens"] == 32
    assert request["stream"] is True
    assert request["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert stream.closed == 2
    assert configured_model.cancellation_scope._closers == {}


def test_ac008_closed_cancelled_stream_cannot_commit_partial_answer(
    configured_model, mocker
):
    stream = ProviderStream([])

    def cancelled_iterator():
        configured_model.stop_event.set()
        return iter([])

    mocker.patch.object(ProviderStream, "__iter__", side_effect=cancelled_iterator)
    mocker.patch.object(
        configured_model, "_dispatch_chat_completion", return_value=stream
    )
    with pytest.raises(RunTerminated):
        NativeModel(configured_model).generate([{"role": "user", "content": "Cancel"}])
    assert stream.closed == 1
    assert configured_model.cancellation_scope._closers == {}


def test_ac008_transient_provider_failure_retries_before_any_tool_execution(
    configured_model, mocker
):
    class ServiceUnavailable(Exception):
        status_code = 503

    configured_model.retry_config = ModelRetryConfig(
        max_attempts=2, backoff_base_seconds=0, jitter=False
    )
    stream = ProviderStream(
        [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="Recovered", tool_calls=None), finish_reason="stop"
                    )
                ],
                usage=None,
            )
        ]
    )
    dispatch = mocker.patch.object(
        configured_model,
        "_dispatch_chat_completion",
        side_effect=[ServiceUnavailable(), stream],
    )
    assert (
        NativeModel(configured_model)
        .generate([{"role": "user", "content": "Retry"}])
        .content
        == "Recovered"
    )
    assert dispatch.call_count == 2
    assert configured_model.last_retry_count == 1
    assert stream.closed == 1


def test_ac008_authentication_failure_does_not_retry(configured_model, mocker):
    class AuthenticationFailure(Exception):
        status_code = 401

    dispatch = mocker.patch.object(
        configured_model,
        "_dispatch_chat_completion",
        side_effect=AuthenticationFailure(),
    )
    with pytest.raises(ModelInvocationTerminalError) as error:
        NativeModel(configured_model).generate(
            [{"role": "user", "content": "Authenticate"}]
        )
    assert error.value.error_code == ModelErrorCode.AUTHENTICATION_ERROR
    assert error.value.attempts == 1
    assert dispatch.call_count == 1


def test_ac003_native_thinking_toggle_uses_existing_provider_adapter(
    configured_model, mocker
):
    configured_model.extra_body = {"enable_thinking": True}
    mocker.patch.object(
        configured_model,
        "_reasoning_wire_profile",
        return_value={"toggle": "thinking_object"},
    )
    stream = ProviderStream(
        [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="Done", tool_calls=None), finish_reason="stop"
                    )
                ],
                usage=None,
            )
        ]
    )
    dispatch = mocker.patch.object(
        configured_model, "_dispatch_chat_completion", return_value=stream
    )
    NativeModel(configured_model).generate([{"role": "user", "content": "Think"}])
    assert dispatch.call_args.kwargs["extra_body"] == {"thinking": {"type": "enabled"}}


def test_ac008_pre_cancelled_model_never_dispatches(configured_model, mocker):
    dispatch = mocker.patch.object(configured_model, "_dispatch_chat_completion")
    configured_model.cancellation_scope.cancel()
    with pytest.raises(RunTerminated):
        NativeModel(configured_model).generate(
            [{"role": "user", "content": "Cancelled"}]
        )
    dispatch.assert_not_called()


def test_ac008_cancellation_racing_provider_failure_is_not_retried(
    configured_model, mocker
):
    def interrupted(**kwargs):
        configured_model.cancellation_scope.cancel()
        raise ConnectionError("Closed by cancellation")

    dispatch = mocker.patch.object(
        configured_model, "_dispatch_chat_completion", side_effect=interrupted
    )
    with pytest.raises(RunTerminated):
        NativeModel(configured_model).generate([{"role": "user", "content": "Cancel"}])
    assert dispatch.call_count == 1


def test_ac008_cancellation_during_backoff_stops_before_second_request(
    configured_model, mocker
):
    class TemporaryUnavailable(Exception):
        status_code = 503

    configured_model.retry_config = ModelRetryConfig(
        max_attempts=2, backoff_base_seconds=0, jitter=False
    )
    dispatch = mocker.patch.object(
        configured_model,
        "_dispatch_chat_completion",
        side_effect=TemporaryUnavailable(),
    )

    def cancel_during_wait(delay):
        configured_model.cancellation_scope.cancel()
        return True

    mocker.patch.object(
        configured_model.stop_event, "wait", side_effect=cancel_during_wait
    )
    with pytest.raises(RunTerminated):
        NativeModel(configured_model).generate(
            [{"role": "user", "content": "Cancel retry"}]
        )
    assert dispatch.call_count == 1


def test_ac008_real_concurrency_limit_is_preserved_without_provider_dispatch(
    configured_model, mocker
):
    from nexent.core.models.model_concurrency import (
        ModelConcurrencyExceeded,
        model_concurrency_limiter,
    )

    permit = model_concurrency_limiter.acquire(
        configured_model.concurrency_key, 1, 0.01, configured_model.stop_event
    )
    dispatch = mocker.patch.object(configured_model, "_dispatch_chat_completion")
    try:
        with pytest.raises(ModelConcurrencyExceeded):
            NativeModel(configured_model).generate(
                [{"role": "user", "content": "Busy"}]
            )
        dispatch.assert_not_called()
    finally:
        permit.release()


def test_ac003_headless_adapter_preserves_canonical_schema_without_optional_controls(
    configured_model, mocker
):
    configured_model.observer = None
    configured_model.extra_body = None
    configured_model.max_output_tokens = None
    configured_model.concurrency_limit = None
    schema = {
        "type": "function",
        "function": {
            "name": "echo",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    stream = ProviderStream(
        [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="Done", tool_calls=None), finish_reason="stop"
                    )
                ],
                usage=None,
            )
        ]
    )
    dispatch = mocker.patch.object(
        configured_model, "_dispatch_chat_completion", return_value=stream
    )
    message = NativeModel(configured_model).generate(
        [{"role": "user", "content": "Answer"}], native_tool_schemas=[schema]
    )
    assert message.content == "Done"
    assert dispatch.call_args.kwargs["tools"] == [schema]
    assert "extra_body" not in dispatch.call_args.kwargs
    assert "max_tokens" not in dispatch.call_args.kwargs
    assert stream.closed == 1


def test_ac008_pre_wrapped_native_model_retains_its_cancellation_scope(
    configured_model,
):
    from nexent.core.agents.native_runtime import NativeToolCallingAgent

    adapter = NativeModel(configured_model)
    agent = NativeToolCallingAgent(model=adapter, tools=[], verbosity_level=0)
    assert agent.model is adapter
    assert agent.stop_event is configured_model.stop_event
