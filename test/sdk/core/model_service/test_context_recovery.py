# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Context-only rebuilds reuse the same frozen sender and physical attempt budget."""

import asyncio
import json
import time
from types import SimpleNamespace

import pytest
from nexent.core.concurrency.cancellation import RunCancellationScope, RunTerminated
from nexent.core.model_service.contracts import ModelMessage, ToolDefinition
from nexent.core.model_service.http_contracts import (
    ModelTransportError,
    RawHttpResponse,
)
from nexent.core.model_service.service import ModelServiceError
from nexent.core.model_service.sse import SSEEvent
from test_model_service import Sender, frame
from test_model_service import setup as setup  # noqa: PLC0414 - Shared pytest fixture.


def overflow():
    return ModelTransportError('HTTP_RESPONSE_STATUS', response=RawHttpResponse(
        400, {}, b'{"error":{"code":"context_length_exceeded","message":"private-detail"}}',
    ))


async def consume(model, request, profile, asynchronous, **kwargs):
    if asynchronous:
        async with model.astream(request, profile, **kwargs) as events:
            return [event async for event in events]
    with model.stream(request, profile, **kwargs) as events:
        return list(events)


@pytest.mark.asyncio
@pytest.mark.parametrize('asynchronous', [False, True])
@pytest.mark.parametrize('succeeds', [False, True])
async def test_context_recovery_shares_http_retry_budget_after_releasing_permit(setup, asynchronous, succeeds):
    profile, request, limiter, factory = setup
    request = request.model_copy(update={'stream': True})
    final = [frame({'content': 'answer'}), frame(finish='stop'), SSEEvent('[DONE]')]
    sender = Sender([ModelTransportError('HTTP_NETWORK_ERROR'), overflow(), final if succeeds else overflow()])
    rebuilds = []

    def rebuild(error):
        assert not limiter._entries and sender.closed == 2
        assert error.attempt == 2 and error.category == 'MODEL_CONTEXT_EXCEEDED'
        rebuilds.append(error)
        return request.model_copy(update={'messages': [ModelMessage(semantic_role='user', content_parts=[{'type': 'text', 'text': 'short'}])]})

    async def arebuild(error):
        return rebuild(error)

    events = await consume(factory(sender), request, profile, asynchronous, request_rebuild=arebuild if asynchronous else rebuild)
    assert events[-1].type == ('message_completed' if succeeds else 'error')
    assert events[-1].attempt == 3
    assert len(sender.calls) == 3 and len(rebuilds) == sender.frozen == 1
    assert sender.calls[0].body_bytes == sender.calls[1].body_bytes
    assert json.loads(sender.calls[2].body_bytes)['messages'] == [{'role': 'user', 'content': 'short'}]
    assert not limiter._entries


@pytest.mark.asyncio
@pytest.mark.parametrize('asynchronous', [False, True])
async def test_context_recovery_is_limited_to_two_even_with_larger_http_budget(setup, asynchronous):
    profile, request, limiter, factory = setup
    request = request.model_copy(update={'stream': True})
    sender = Sender([overflow(), overflow(), overflow()])
    model = factory(sender)
    model._policy = SimpleNamespace(max_attempts=5, calculate_backoff=lambda _: 0)
    rebuilds = []

    def rebuild(error):
        rebuilds.append(error)
        return request

    async def arebuild(error):
        return rebuild(error)

    events = await consume(model, request, profile, asynchronous, request_rebuild=arebuild if asynchronous else rebuild)
    assert len(sender.calls) == 3 and len(rebuilds) == 2
    assert events[-1].error.category == 'MODEL_CONTEXT_EXCEEDED' and not events[-1].error.will_retry
    assert not limiter._entries


@pytest.mark.parametrize('change', [None, {'request_id': 'other'}, {'outlet_id': 7}, {'purpose': 'other'}, {'config_revision': 2}, {'stream': False}, {'tools': [ToolDefinition(name='changed', description='changed tool', input_schema={'type': 'object'})]}])
def test_invalid_rebuild_never_dispatches_another_request(setup, change):
    profile, request, limiter, factory = setup
    request = request.model_copy(update={'stream': True})
    sender = Sender([overflow()])
    callback = lambda _: None if change is None else request.model_copy(update=change)
    with pytest.raises((TypeError, ValueError)), factory(sender).stream(request, profile, request_rebuild=callback) as events:
        list(events)
    assert len(sender.calls) == 1 and sender.closed == 1 and not limiter._entries


def test_cancellation_during_sync_rebuild_never_dispatches_again(setup):
    profile, request, limiter, factory = setup
    sender = Sender([overflow()])
    scope = RunCancellationScope()

    def rebuild(_error):
        scope.cancel()
        return request

    with pytest.raises(RunTerminated):
        factory(sender).invoke(request, profile, scope=scope, request_rebuild=rebuild)
    assert len(sender.calls) == 1 and not limiter._entries


@pytest.mark.asyncio
async def test_async_rebuild_is_bounded_by_original_run_deadline(setup):
    profile, request, limiter, factory = setup
    sender = Sender([overflow()])
    exited = asyncio.Event()

    async def rebuild(_error):
        try:
            await asyncio.Event().wait()
        finally:
            exited.set()

    with pytest.raises(ModelServiceError) as caught:
        await factory(sender).ainvoke(request, profile, request_rebuild=rebuild, deadline=time.monotonic() + 0.1)
    assert caught.value.error.category == 'MODEL_RUN_DEADLINE'
    assert exited.is_set() and len(sender.calls) == 1 and not limiter._entries


@pytest.mark.asyncio
@pytest.mark.parametrize('asynchronous', [False, True])
async def test_visible_reasoning_forbids_context_rebuild(setup, asynchronous):
    profile, request, limiter, factory = setup
    request = request.model_copy(update={'stream': True})
    sender = Sender([[frame({'reasoning_content': 'thought'}), overflow()]])
    called = []

    def rebuild(error):
        called.append(error)
        return request

    async def arebuild(error):
        return rebuild(error)

    events = await consume(factory(sender), request, profile, asynchronous, request_rebuild=arebuild if asynchronous else rebuild)
    assert events[0].type == 'reasoning_delta'
    assert events[-1].error.category == 'MODEL_CONTEXT_EXCEEDED'
    assert not called and len(sender.calls) == 1 and not limiter._entries


@pytest.mark.asyncio
async def test_wrong_callback_type_is_rejected_before_credentials_or_send(setup):
    profile, request, limiter, factory = setup
    sender = Sender([])
    model = factory(sender)

    async def asynchronous(_error):
        return request

    with pytest.raises(TypeError, match='callback'):
        model.invoke(request, profile, request_rebuild=asynchronous)
    with pytest.raises(TypeError, match='callback'):
        await model.ainvoke(request, profile, request_rebuild=lambda _: request)
    assert not sender.calls and not sender.frozen and not limiter._entries


@pytest.mark.asyncio
async def test_scope_cancel_interrupts_suspended_async_rebuild_and_unregisters_hook(setup):
    profile, request, limiter, factory = setup
    sender = Sender([overflow()])
    scope = RunCancellationScope()
    started, exited = asyncio.Event(), asyncio.Event()

    async def rebuild(_error):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            exited.set()

    async def cancel():
        await started.wait()
        scope.cancel()

    async with asyncio.TaskGroup() as group:
        group.create_task(cancel())
        with pytest.raises(RunTerminated):
            await factory(sender).ainvoke(request, profile, scope=scope, request_rebuild=rebuild)
    assert exited.is_set() and len(sender.calls) == 1
    assert not limiter._entries and not scope._closers


def test_callback_error_is_not_retried_as_an_http_error(setup):
    profile, request, limiter, factory = setup
    sender = Sender([overflow()])

    def rebuild(_error):
        raise RuntimeError('context construction failed')

    with pytest.raises(RuntimeError, match='context construction failed'):
        factory(sender).invoke(request, profile, request_rebuild=rebuild)
    assert len(sender.calls) == 1 and not limiter._entries


def test_sync_rebuild_cannot_dispatch_after_original_deadline(setup, monkeypatch):
    profile, request, limiter, factory = setup
    sender = Sender([overflow()])
    now = [time.monotonic()]
    monkeypatch.setattr('nexent.core.model_service.service.time.monotonic', lambda: now[0])

    def rebuild(_error):
        now[0] += 2
        return request

    with pytest.raises(ModelServiceError) as caught:
        factory(sender).invoke(request, profile, request_rebuild=rebuild, deadline=now[0] + 1)
    assert caught.value.error.category == 'MODEL_RUN_DEADLINE'
    assert len(sender.calls) == 1 and not limiter._entries
