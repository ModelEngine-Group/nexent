# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Regression tests for producer ownership before any SSE body is consumed."""

import asyncio
import importlib.util
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import Request

from . import test_agent_service as service_tests


@pytest_asyncio.fixture
async def lifecycle(monkeypatch):
    service = service_tests.agent_subscription
    producer = service_tests.agent_execution
    # Load a fresh real manager without changing the legacy suite's SDK/DB stubs.
    path = Path(__file__).resolve().parents[3] / "backend/agents/agent_run_manager.py"
    spec = importlib.util.spec_from_file_location("subscription_lifecycle_manager", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manager = module.AgentRunManager()
    monkeypatch.setattr(service, "agent_run_manager", manager)
    monkeypatch.setattr(producer, "agent_run_manager", manager)
    monkeypatch.setattr(service, "AgentRunAlreadyActiveError", module.AgentRunAlreadyActiveError)
    monkeypatch.setattr(service, "_resolve_user_tenant_language", MagicMock(return_value=("u", "t", "en")))
    monkeypatch.setattr(service, "get_conversation_service", MagicMock(return_value={"conversation_id": 123}))
    monkeypatch.setattr(service, "create_new_conversation", MagicMock(return_value={"conversation_id": 123}))
    monkeypatch.setattr(service, "save_messages", MagicMock())
    monkeypatch.setattr(service, "build_agent_run_context", MagicMock(return_value=SimpleNamespace(
        metadata={}, enable_memory=False,
    )))
    future = Future()
    execution = SimpleNamespace(future=future, execution_id="lifecycle-worker")
    deferred = MagicMock()
    monkeypatch.setattr(service, "DeferredAgentRun", MagicMock(return_value=deferred))
    monkeypatch.setattr(service.runtime_thread_manager, "submit", MagicMock(return_value=execution))
    monkeypatch.setattr(service.runtime_thread_manager, "wait_until_started", AsyncMock())
    cancel = MagicMock(side_effect=lambda *_args, **_kwargs: future.cancel())
    monkeypatch.setattr(service.runtime_thread_manager, "cancel", cancel)
    channel = service_tests.AsyncChannelMock()
    monkeypatch.setattr(service.streaming_channel_manager, "get_or_create_channel", AsyncMock(return_value=channel))

    async def complete_channel(**kwargs):
        channel.complete(kwargs["status"])

    monkeypatch.setattr(producer.streaming_channel_manager, "complete_channel", AsyncMock(side_effect=complete_channel))
    monkeypatch.setattr(producer, "_cleanup_channel_later", AsyncMock())
    request = service_tests.AgentRequest(
        agent_id=1, conversation_id=None, query="test", history=[], minio_files=[], is_debug=False,
    )
    env = SimpleNamespace(
        service=service, manager=manager, errors=module, future=future,
        execution=execution, deferred=deferred, cancel=cancel, channel=channel, request=request,
    )

    async def start(source, **options):
        monkeypatch.setattr(service, "generate_stream", source)
        return await service.run_agent_stream(request, Request({"type": "http", "headers": []}), "token", **options)

    env.start = start
    yield env
    tasks = list(service._agent_stream_producer_tasks)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await asyncio.sleep(0)
    future.cancel()


@pytest.mark.asyncio
async def test_headers_only_response_starts_producer_and_replays_completed_history(lifecycle):
    env = lifecycle
    calls = []

    async def source(_request, **_kwargs):
        calls.append("run")
        await env.channel.publish("data: answer\n\n")
        yield "data: answer\n\n"
        env.channel.complete()
        env.future.set_result(None)

    response = await env.start(source)
    assert response.headers["conversation_id"] == "123"
    tasks = list(env.service._agent_stream_producer_tasks)
    assert len(tasks) == 1
    # No response iterator has been started, as in a headers-only HTTP client.
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=1)
    await asyncio.sleep(0)
    assert calls == ["run"]
    assert not env.manager._reservations
    assert not env.service._agent_stream_producer_tasks
    assert env.manager.get_agent_capacity_count(1) == 0
    env.cancel.assert_not_called()
    env.deferred.cancel.assert_not_called()
    chunks = [chunk async for chunk in response.body_iterator]
    assert "conversation_created" in chunks[0]
    assert chunks[1:] == ["data: answer\n\n"]


@pytest.mark.asyncio
async def test_disconnect_during_preparation_preserves_reservation_and_rejects_duplicate(lifecycle):
    env = lifecycle
    preparing = asyncio.Event()
    proceed = asyncio.Event()
    registered = []

    async def source(_request, **kwargs):
        preparing.set()
        await proceed.wait()
        info = SimpleNamespace()
        env.manager.register_agent_run(123, info, "u", reservation_token=kwargs["reservation_token"])
        registered.append(info)
        env.manager.unregister_agent_run(123, "u", agent_run_info=info)
        env.channel.complete()
        env.future.set_result(None)
        yield "done"

    response = await env.start(source)
    assert "conversation_created" in await anext(response.body_iterator)
    await asyncio.wait_for(preparing.wait(), timeout=1)
    await response.body_iterator.aclose()
    with pytest.raises(env.errors.AgentRunAlreadyActiveError):
        env.manager.reserve_agent_run(123, "u")
    assert not env.future.done()
    env.cancel.assert_not_called()
    proceed.set()
    await asyncio.wait_for(asyncio.gather(*env.service._agent_stream_producer_tasks), timeout=1)
    await asyncio.sleep(0)
    assert len(registered) == 1
    assert env.channel.completion_status == "completed"
    assert not env.manager._reservations
    assert not env.manager.agent_runs


@pytest.mark.asyncio
async def test_preparation_failure_releases_reservation_worker_and_capacity(lifecycle):
    env = lifecycle

    async def source(_request, **_kwargs):
        raise RuntimeError("private provider details")
        yield "unreachable"

    response = await env.start(source)
    await asyncio.wait_for(asyncio.gather(*env.service._agent_stream_producer_tasks), timeout=1)
    await asyncio.sleep(0)
    assert env.channel.completion_status == "failed"
    assert len(env.channel._history) == 1
    assert "private provider details" not in env.channel._history[0]
    assert not env.manager._reservations
    assert not env.service._agent_stream_producer_tasks
    assert env.future.cancelled()
    assert env.manager.get_agent_capacity_count(1) == 0
    env.deferred.cancel.assert_called_once()
    env.cancel.assert_called_once()
    await response.body_iterator.aclose()


@pytest.mark.asyncio
async def test_completed_producer_does_not_cancel_bound_worker_cleanup(lifecycle):
    env = lifecycle

    async def source(_request, **kwargs):
        # Real preparation consumes this reservation when binding the worker.
        env.manager.register_agent_run(123, SimpleNamespace(), "u", kwargs["reservation_token"])
        env.channel.complete()
        yield "done"

    response = await env.start(source)
    await asyncio.wait_for(asyncio.gather(*env.service._agent_stream_producer_tasks), timeout=1)
    await asyncio.sleep(0)
    assert not env.future.done()
    assert env.manager.get_agent_capacity_count(1) == 1
    env.cancel.assert_not_called()
    env.deferred.cancel.assert_not_called()
    env.future.set_result(None)
    assert env.manager.get_agent_capacity_count(1) == 0
    await response.body_iterator.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("after_start", [False, True])
async def test_producer_cancellation_releases_preparation_even_before_first_iteration(lifecycle, after_start):
    env = lifecycle
    started = asyncio.Event()
    closed = asyncio.Event()

    async def source(_request, **_kwargs):
        try:
            started.set()
            await asyncio.Event().wait()
            yield "unreachable"
        finally:
            closed.set()

    response = await env.start(source)
    tasks = list(env.service._agent_stream_producer_tasks)
    assert len(tasks) == 1
    if after_start:
        await asyncio.wait_for(started.wait(), timeout=1)
    tasks[0].cancel()
    with pytest.raises(asyncio.CancelledError):
        await tasks[0]
    await asyncio.sleep(0)
    assert closed.is_set() == after_start
    assert not env.manager._reservations
    assert not env.service._agent_stream_producer_tasks
    assert env.future.cancelled()
    assert env.manager.get_agent_capacity_count(1) == 0
    env.deferred.cancel.assert_called_once()
    env.cancel.assert_called_once()
    await response.body_iterator.aclose()


@pytest.mark.asyncio
async def test_debug_disconnect_still_cancels_direct_worker(lifecycle):
    env = lifecycle
    env.request.is_debug = True
    env.request.conversation_id = 123

    async def source(_request, **_kwargs):
        yield "data: debug\n\n"
        await asyncio.Event().wait()

    response = await env.start(source)
    assert not env.service._agent_stream_producer_tasks
    assert await anext(response.body_iterator) == "data: debug\n\n"
    await response.body_iterator.aclose()
    env.deferred.cancel.assert_called_once()
    env.cancel.assert_called_once()
    assert not env.manager._reservations
    assert env.future.cancelled()


@pytest.mark.asyncio
async def test_explicit_stop_after_subscriber_disconnect_still_reaches_worker(lifecycle):
    env = lifecycle
    started = asyncio.Event()
    info = SimpleNamespace(
        stop_event=asyncio.Event(), cancellation_scope=MagicMock(),
        thread_manager=env.service.runtime_thread_manager,
        thread_execution_id=env.execution.execution_id,
    )

    async def source(_request, **kwargs):
        env.manager.register_agent_run(123, info, "u", kwargs["reservation_token"])
        started.set()
        await info.stop_event.wait()
        env.manager.unregister_agent_run(123, "u", status="stopped", agent_run_info=info)
        env.channel.complete("stopped")
        yield "stopped"

    response = await env.start(source)
    await anext(response.body_iterator)
    await asyncio.wait_for(started.wait(), timeout=1)
    await response.body_iterator.aclose()
    env.cancel.assert_not_called()
    assert env.manager.stop_agent_run(123, "u") is True
    await asyncio.wait_for(asyncio.gather(*env.service._agent_stream_producer_tasks), timeout=1)
    info.cancellation_scope.cancel.assert_called_once()
    env.cancel.assert_called_once()
    assert env.channel.completion_status == "stopped"
    assert env.future.cancelled()
    assert not env.manager.agent_runs
