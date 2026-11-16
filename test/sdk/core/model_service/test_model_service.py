# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Logical call policy with controlled transport failures and real adapter contracts."""

import asyncio
import json
import time
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace

import pytest
from nexent.core.concurrency.cancellation import RunCancellationScope, RunTerminated
from nexent.core.model_service.adapters.openai_chat import OpenAIChatAdapter
from nexent.core.model_service.concurrency import ModelConcurrencyLimiter
from nexent.core.model_service.contracts import ModelMessage, ModelRequest
from nexent.core.model_service.http_contracts import (
    ModelTransportError,
    RawHttpResponse,
)
from nexent.core.model_service.service import (
    ModelRequestRetryPolicy,
    ModelService,
    ModelServiceError,
)
from nexent.core.model_service.sse import SSEEvent


def complete():
    return RawHttpResponse(
        200,
        {},
        json.dumps(
            {
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "answer",
                        },
                        "finish_reason": "stop",
                    }
                ]
            }
        ).encode(),
    )


def frame(delta=None, finish=None):
    return SSEEvent(
        json.dumps(
            {"choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}]}
        )
    )


class Sender:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = []
        self.closed = 0
        self.frozen = 0

    def freeze_credentials(self, request):
        self.frozen += 1
        return self

    def invoke(self, request, **kwargs):
        self.calls.append(request)
        outcome = next(self.outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def ainvoke(self, request, **kwargs):
        return self.invoke(request, **kwargs)

    @contextmanager
    def stream(self, request, **kwargs):
        def events():
            for event in self.invoke(request):
                if isinstance(event, BaseException):
                    raise event
                yield event

        try:
            yield events()
        finally:
            self.closed += 1

    @asynccontextmanager
    async def astream(self, request, **kwargs):
        async def events():
            for event in self.invoke(request):
                if isinstance(event, BaseException):
                    raise event
                yield event

        try:
            yield events()
        finally:
            self.closed += 1


@pytest.fixture
def setup(openai_profile):
    values = openai_profile.model_dump()
    values["bindings"]["adapter"] = OpenAIChatAdapter.reference.model_dump()
    values["connection"]["concurrency_limit"] = 1
    profile = type(openai_profile).model_validate(values)
    request = ModelRequest(
        request_id="logical-request",
        outlet_id=None,
        config_revision=1,
        messages=[
            ModelMessage(
                semantic_role="user", content_parts=[{"type": "text", "text": "hello"}]
            ),
        ],
    )
    limiter = ModelConcurrencyLimiter()

    def service(sender, **kwargs):
        return ModelService(
            lambda _: sender,
            limiter=limiter,
            retry_policy=SimpleNamespace(
                max_attempts=3,
                calculate_backoff=lambda _: 0,
            ),
            **kwargs,
        )

    return profile, request, limiter, service


@pytest.mark.asyncio
async def test_sync_async_retry_preserves_snapshot_and_releases_permits(setup):
    profile, request, limiter, service = setup
    for asynchronous in [False, True]:
        sender = Sender([ModelTransportError("HTTP_NETWORK_ERROR"), complete()])
        model = service(sender)
        result = (
            await model.ainvoke(request, profile)
            if asynchronous
            else model.invoke(request, profile)
        )
        assert result.content_parts == [{"type": "text", "text": "answer"}]
        assert len(sender.calls) == 2 and sender.frozen == 1
        assert sender.calls[0].body_bytes == sender.calls[1].body_bytes
        assert (
            sender.calls[0].request_id
            == sender.calls[1].request_id
            == request.request_id
        )
        assert not limiter._entries


@pytest.mark.parametrize("status", [401, 403, 400, 404, 422])
def test_nonretryable_provider_error_is_safe_and_releases_permit(setup, status):
    profile, request, limiter, service = setup
    sender = Sender(
        [
            ModelTransportError(
                "HTTP_STATUS_ERROR",
                response=RawHttpResponse(
                    status,
                    {},
                    b'{"error":{"message":"private-key-123"}}',
                    sensitive_values=("private-key-123",),
                ),
            )
        ]
    )
    with pytest.raises(ModelServiceError) as caught:
        service(sender).invoke(request, profile)
    assert caught.value.error.attempt == 1 and not caught.value.error.will_retry
    assert "private-key" not in str(caught.value) + caught.value.error.model_dump_json()
    assert len(sender.calls) == 1 and not limiter._entries


def test_default_retry_count_is_three_and_exhaustion_is_explicit(setup):
    profile, request, limiter, _ = setup
    sender = Sender([ModelTransportError("HTTP_NETWORK_ERROR") for _ in range(3)])
    policy = SimpleNamespace(
        max_attempts=ModelRequestRetryPolicy().max_attempts,
        calculate_backoff=lambda _: 0,
    )
    with pytest.raises(ModelServiceError) as caught:
        ModelService(lambda _: sender, limiter=limiter, retry_policy=policy).invoke(
            request, profile
        )
    assert len(sender.calls) == caught.value.error.attempt == 3
    assert caught.value.error.retryable and not caught.value.error.will_retry
    assert not limiter._entries


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "delta",
    [
        {"content": "visible"},
        {"reasoning_content": "thinking"},
        {
            "tool_calls": [
                {
                    "index": 0,
                    "id": "call-one",
                    "function": {"name": "tool", "arguments": "{"},
                }
            ],
        },
    ],
)
async def test_any_visible_fragment_prevents_sync_async_stream_replay(setup, delta):
    profile, request, limiter, service = setup
    request = request.model_copy(update={"stream": True})
    for asynchronous in [False, True]:
        sender = Sender([[frame(delta), ModelTransportError("HTTP_NETWORK_ERROR")]])
        if asynchronous:
            async with service(sender).astream(request, profile) as events:
                result = [event async for event in events]
        else:
            with service(sender).stream(request, profile) as events:
                result = list(events)
        assert result[-1].type == "error" and not result[-1].error.will_retry
        assert len(sender.calls) == 1 and sender.closed == 1
        assert [event.sequence for event in result] == list(range(1, len(result) + 1))
        assert not limiter._entries


@pytest.mark.asyncio
async def test_pre_output_stream_retry_then_completion_and_early_exit(setup):
    profile, request, limiter, service = setup
    request = request.model_copy(update={"stream": True})
    for asynchronous in [False, True]:
        sender = Sender(
            [
                ModelTransportError("HTTP_NETWORK_ERROR"),
                [
                    frame({"content": "answer"}),
                    frame(finish="stop"),
                    SSEEvent("[DONE]"),
                ],
            ]
        )
        if asynchronous:
            async with service(sender).astream(request, profile) as events:
                result = [event async for event in events]
        else:
            with service(sender).stream(request, profile) as events:
                result = list(events)
        assert [event.type for event in result] == ["text_delta", "message_completed"]
        assert [event.attempt for event in result] == [2, 2]
        assert len(sender.calls) == sender.closed == 2 and not limiter._entries
    sender = Sender(
        [[frame({"content": "first"}), frame(finish="stop"), SSEEvent("[DONE]")]]
    )
    async with service(sender).astream(request, profile) as events:
        assert (await anext(events)).type == "text_delta"
    assert sender.closed == 1 and not limiter._entries
    with pytest.raises(StopAsyncIteration):
        await anext(events)


@pytest.mark.asyncio
async def test_cancelled_run_never_starts_or_retries(setup):
    profile, request, limiter, service = setup
    sender = Sender([])
    scope = RunCancellationScope()
    scope.cancel()
    with pytest.raises(RunTerminated):
        await service(sender).ainvoke(request, profile, scope=scope)
    assert not sender.calls and not sender.frozen and not limiter._entries


def test_retry_after_exceeding_run_budget_is_not_retried(setup):
    profile, request, limiter, service = setup
    sender = Sender(
        [
            ModelTransportError(
                "HTTP_STATUS_ERROR",
                response=RawHttpResponse(
                    429,
                    {"Retry-After": "30"},
                    b"{}",
                ),
            )
        ]
    )
    with pytest.raises(ModelServiceError) as caught:
        service(sender).invoke(request, profile, deadline=time.monotonic() + 5)
    assert (
        caught.value.error.category == "MODEL_RATE_LIMITED"
        and not caught.value.error.will_retry
    )
    assert len(sender.calls) == 1 and not limiter._entries


@pytest.mark.asyncio
async def test_error_before_first_model_event_has_valid_identity(setup):
    profile, request, limiter, service = setup
    request = request.model_copy(update={"stream": True})
    for asynchronous in [False, True]:
        sender = Sender([[SSEEvent("invalid-json")]])
        if asynchronous:
            async with service(sender).astream(request, profile) as events:
                result = [event async for event in events]
        else:
            with service(sender).stream(request, profile) as events:
                result = list(events)
        assert len(result) == 1 and result[0].type == "error"
        assert result[0].error.category == "MODEL_PROTOCOL_ERROR"
        assert result[0].sequence == 1 and not limiter._entries


@pytest.mark.asyncio
async def test_async_task_cancellation_releases_admission(setup):
    profile, request, limiter, service = setup
    sender = Sender([])
    entered = asyncio.Event()

    async def blocked(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    sender.ainvoke = blocked
    task = asyncio.create_task(service(sender).ainvoke(request, profile))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not limiter._entries


@pytest.mark.asyncio
async def test_async_run_deadline_interrupts_blocked_call_without_retry(setup, caplog):
    profile, request, limiter, service = setup
    sender = Sender([])
    cancelled = asyncio.Event()

    async def blocked(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    sender.ainvoke = blocked
    with pytest.raises(ModelServiceError) as caught:
        await service(sender).ainvoke(
            request, profile, deadline=time.monotonic() + 0.05
        )
    assert caught.value.error.category == "MODEL_RUN_DEADLINE"
    assert caught.value.error.attempt == 1 and not caught.value.error.will_retry
    assert cancelled.is_set() and not limiter._entries
    assert [record.message for record in caplog.records] == ["model_request_timeout"]
    assert caplog.records[0].levelname == "WARNING"


def test_stream_uses_snapshot_detached_at_context_entry(setup):
    profile, request, limiter, service = setup
    request = request.model_copy(update={"stream": True})
    sender = Sender(
        [[frame({"content": "answer"}), frame(finish="stop"), SSEEvent("[DONE]")]]
    )
    with service(sender).stream(request, profile) as events:
        profile.parameter_values["enable_thinking"] = True
        request.messages[0].content_parts[0]["text"] = "changed"
        assert list(events)[-1].type == "message_completed"
    body = json.loads(sender.calls[0].body_bytes)
    assert body["enable_thinking"] is False
    assert body["messages"][0]["content"] == "hello"
    assert not limiter._entries


@pytest.mark.asyncio
@pytest.mark.parametrize('asynchronous', [False, True])
@pytest.mark.parametrize('policy,expected_calls,terminal', [
    ('accept', 1, 'message_completed'),
    ('fail', 1, 'error'),
    ('retry', 3, 'error'),
])
async def test_empty_response_policy_shares_physical_retry_budget(setup, asynchronous, policy, expected_calls, terminal):
    profile, request, limiter, factory = setup
    request = request.model_copy(update={'stream': True})
    # A network failure and two empty completions consume the same three attempts.
    empty = [frame(finish='stop'), SSEEvent('[DONE]')]
    outcomes = [ModelTransportError('HTTP_NETWORK_ERROR'), empty, empty] if policy == 'retry' else [empty]
    sender = Sender(outcomes)
    model = factory(sender)
    if asynchronous:
        async with model.astream(request, profile, empty_response_policy=policy) as stream:
            events = [event async for event in stream]
    else:
        with model.stream(request, profile, empty_response_policy=policy) as stream:
            events = list(stream)
    assert events[-1].type == terminal
    if terminal == 'error':
        assert events[-1].error.category == 'MODEL_EMPTY_RESPONSE'
        assert events[-1].error.attempt == expected_calls
        assert not events[-1].error.will_retry
    assert len(sender.calls) == expected_calls and sender.frozen == 1
    assert all(call.body_bytes == sender.calls[0].body_bytes for call in sender.calls)
    assert not limiter._entries


@pytest.mark.asyncio
@pytest.mark.parametrize('asynchronous', [False, True])
@pytest.mark.parametrize('delta,finish,terminal', [
    ({'reasoning_content': 'thought'}, 'stop', 'error'),
    ({'content': '   '}, 'stop', 'error'),
    ({}, 'length', 'error'),
    ({}, None, 'error'),
    ({'refusal': 'cannot comply'}, 'stop', 'message_completed'),
    ({'content': 'answer'}, 'stop', 'message_completed'),
])
async def test_empty_policy_never_replays_visible_output_or_nonstop_finish(setup, asynchronous, delta, finish, terminal):
    profile, request, limiter, factory = setup
    request = request.model_copy(update={'stream': True})
    sender = Sender([[frame(delta), frame(finish=finish), SSEEvent('[DONE]')]])
    model = factory(sender)
    if asynchronous:
        async with model.astream(request, profile, empty_response_policy='retry') as stream:
            events = [event async for event in stream]
    else:
        with model.stream(request, profile, empty_response_policy='retry') as stream:
            events = list(stream)
    assert events[-1].type == terminal
    assert len(sender.calls) == 1 and not limiter._entries


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("max_attempts", [1, 3, 5])
async def test_empty_stop_has_only_one_retry_within_total_budget(setup, asynchronous, max_attempts):
    profile, request, limiter, _factory = setup
    request = request.model_copy(update={"stream": True})
    sender = Sender([[frame(finish="stop"), SSEEvent("[DONE]")]] * max_attempts)
    model = ModelService(lambda _: sender, limiter=limiter, retry_policy=SimpleNamespace(
        max_attempts=max_attempts, calculate_backoff=lambda _: 0,
    ))
    if asynchronous:
        async with model.astream(request, profile, empty_response_policy="retry") as stream:
            events = [event async for event in stream]
    else:
        with model.stream(request, profile, empty_response_policy="retry") as stream:
            events = list(stream)
    assert len(sender.calls) == min(2, max_attempts)
    assert events[-1].error.category == "MODEL_EMPTY_RESPONSE"
    assert not events[-1].error.will_retry
    assert not limiter._entries
