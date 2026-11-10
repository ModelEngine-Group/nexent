# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Regression tests for producer ownership before any SSE body is consumed."""

import asyncio
import importlib.util
import threading
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
    path = Path(__file__).resolve().parents[3] / "backend/runtime/executions.py"
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

    async def start(source):
        monkeypatch.setattr(service, "generate_stream", source)
        return await service.run_agent_stream(request, Request({"type": "http", "headers": []}), "token")

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


@pytest.mark.asyncio
async def test_initial_stream_exposes_run_id_without_changing_legacy_sse(lifecycle, monkeypatch):
    env = lifecycle
    run_id = "a" * 32
    monkeypatch.setattr(env.service.runtime_state_service, "enabled", True)
    async def start_journal(_tenant, selected_run_id):
        return selected_run_id

    monkeypatch.setattr(env.service.uuid, "uuid4", lambda: SimpleNamespace(hex=run_id))
    monkeypatch.setattr(env.channel, "start_journal", AsyncMock(side_effect=start_journal), raising=False)

    async def source(_request, **_kwargs):
        await env.channel.publish("data: answer\n\n")
        yield "data: answer\n\n"
        env.channel.complete()
        env.future.set_result(None)

    response = await env.start(source)

    assert response.headers["X-AgentOS-Run-ID"] == run_id
    env.channel.start_journal.assert_awaited_once_with("t", run_id)
    assert env.request._projection_run_id == run_id
    chunks = [chunk async for chunk in response.body_iterator]
    assert "conversation_created" in chunks[0]
    assert chunks[1:] == ["data: answer\n\n"]


@pytest.mark.asyncio
async def test_claimed_run_binds_conversation_before_starting_producer(lifecycle, monkeypatch):
    from infrastructure.rdb import agent_admission

    env = lifecycle
    run_id = "a" * 32
    scope = "b" * 64
    env.request._projection_run_id = run_id
    env.request._run_admission_scope = scope
    monkeypatch.setattr(env.service.runtime_state_service, "enabled", True)
    monkeypatch.setattr(env.channel, "start_journal", AsyncMock(return_value=run_id), raising=False)
    order = []

    def record(*args, **kwargs):
        assert args == (scope, run_id, "u", "t")
        assert kwargs == {"conversation_id": 123, "journal_available": True}
        order.append("bound")
        return True

    monkeypatch.setattr(agent_admission, "set_conversation_admission", record)

    async def source(_request, **_kwargs):
        order.append("producer")
        yield "data: answer\n\n"
        env.future.set_result(None)

    response = await env.start(source)
    await asyncio.wait_for(asyncio.gather(*env.service._agent_stream_producer_tasks), timeout=1)

    assert response.headers["X-AgentOS-Run-ID"] == run_id
    env.channel.start_journal.assert_awaited_once_with("t", run_id)
    assert order == ["bound", "producer"]


@pytest.mark.asyncio
async def test_failed_admission_binding_cleans_journal_before_releasing_reservation(lifecycle, monkeypatch):
    from infrastructure.rdb import agent_admission

    env = lifecycle
    env.request._projection_run_id = "a" * 32
    env.request._run_admission_scope = "b" * 64
    monkeypatch.setattr(env.service.runtime_state_service, "enabled", True)
    monkeypatch.setattr(env.channel, "start_journal", AsyncMock(return_value="a" * 32), raising=False)
    monkeypatch.setattr(env.channel, "finish_journal", AsyncMock(), raising=False)
    monkeypatch.setattr(agent_admission, "set_conversation_admission", lambda *args, **kwargs: False)

    async def remove(conversation_id, user_id, *, expected_channel):
        assert (conversation_id, user_id, expected_channel) == (123, "u", env.channel)
        assert env.manager._reservations

    monkeypatch.setattr(env.service.streaming_channel_manager, "remove_channel", AsyncMock(side_effect=remove))
    source = MagicMock()

    with pytest.raises(RuntimeError, match="claim is no longer pending"):
        await env.start(source)

    env.channel.finish_journal.assert_awaited_once_with("failed")
    source.assert_not_called()
    assert not env.manager._reservations
    assert not env.service._agent_stream_producer_tasks
    assert env.future.cancelled()


@pytest.mark.asyncio
async def test_agentos_stop_during_preparation_releases_worker_after_terminal_publication(lifecycle, monkeypatch):
    env = lifecycle
    execution = service_tests.agent_execution
    run = service_tests.agent_run_service
    run_id = "a" * 32
    env.channel.run_journal = execution.RunJournal("t", "u", 123, run_id)
    preparing = asyncio.Event()
    stop = asyncio.Event()

    async def prepare(**kwargs):
        preparing.set()
        await asyncio.Future()

    async def poll_stop(journal):
        assert journal is env.channel.run_journal
        return stop.is_set()

    async def complete_channel(**kwargs):
        assert env.manager._reservations
        env.channel.complete(kwargs["status"])

    monkeypatch.setattr(run, "agent_run_manager", env.manager)
    monkeypatch.setattr(run, "prepare_agent_run", prepare)
    monkeypatch.setattr(run, "_stream_agent_chunks", MagicMock())
    monkeypatch.setattr(run, "_journal_stop_requested", poll_stop)
    monkeypatch.setattr(execution, "_journal_stop_requested", poll_stop)
    monkeypatch.setattr(execution, "RUNTIME_CANCEL_POLL_INTERVAL_SECONDS", 0.001)
    monkeypatch.setattr(execution.streaming_channel_manager, "complete_channel", complete_channel)

    await env.start(run.generate_stream)
    producer, = env.service._agent_stream_producer_tasks
    await asyncio.wait_for(preparing.wait(), timeout=1)
    stop.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(asyncio.shield(producer), timeout=1)
    assert producer.cancelled()
    assert env.channel.completion_status == "stopped"
    assert not env.manager._reservations
    assert env.future.cancelled()
    run._stream_agent_chunks.assert_not_called()


@pytest.mark.asyncio
async def test_agentos_worker_polls_only_its_own_run_id(monkeypatch):
    execution = service_tests.agent_execution
    first = execution.RunJournal("t", "u", 123, "a" * 32)
    next_run = execution.RunJournal("t", "u", 123, "b" * 32)
    scoped_reads = []

    async def poll_stop(journal):
        scoped_reads.append(journal)
        return journal == first

    legacy_signal = AsyncMock(return_value=False)
    monkeypatch.setattr(execution.runtime_state_service, "is_cancelled_async", legacy_signal)
    monkeypatch.setattr(execution, "_journal_stop_requested", poll_stop)
    old_event, next_event = threading.Event(), threading.Event()
    old_scope, next_scope = MagicMock(), MagicMock()
    next_poll = asyncio.create_task(execution._poll_runtime_cancel_signal(
        123, "u", next_event, next_scope, journal=next_run,
    ))
    try:
        await asyncio.sleep(0)
        await execution._poll_runtime_cancel_signal(123, "u", old_event, old_scope, journal=first)
        assert old_event.is_set() and not next_event.is_set()
        old_scope.cancel.assert_called_once_with()
        next_scope.cancel.assert_not_called()
        assert scoped_reads == [next_run, first]
        legacy_signal.assert_awaited_once_with(user_id="u", conversation_id=123)
    finally:
        next_poll.cancel()
        await asyncio.gather(next_poll, return_exceptions=True)


@pytest.mark.asyncio
async def test_agentos_stop_between_preparation_and_sdk_dispatch(lifecycle, monkeypatch):
    env = lifecycle
    worker = service_tests.agent_execution
    run = service_tests.agent_run_service
    env.channel.run_journal = worker.RunJournal("t", "u", 123, "a" * 32)
    info = SimpleNamespace(stop_event=threading.Event(), cancellation_scope=None, agent_config=SimpleNamespace())
    prepared = False

    async def prepare(**kwargs):
        nonlocal prepared
        env.manager.register_agent_run(123, info, "u", kwargs["reservation_token"])
        prepared = True
        return info, None

    async def poll_stop(journal):
        return prepared

    monkeypatch.setattr(run, "agent_run_manager", env.manager)
    monkeypatch.setattr(run, "prepare_agent_run", prepare)
    monkeypatch.setattr(run, "_journal_stop_requested", poll_stop)
    monkeypatch.setattr(worker, "_journal_stop_requested", poll_stop)
    monkeypatch.setattr(worker, "save_message", MagicMock(return_value=7))
    async def finalize_projection(**kwargs):
        assert kwargs["terminal_status"] == "stopped"
        return "stopped", False, ""

    monkeypatch.setattr(worker, "finalize_assistant_projection", finalize_projection)
    monkeypatch.setattr(worker, "agent_run", MagicMock())
    env.deferred.cancel.side_effect = lambda: env.future.set_result(None)

    await env.start(run.generate_stream)
    producer, = env.service._agent_stream_producer_tasks
    await asyncio.wait_for(producer, timeout=1)
    assert env.channel.completion_status == "stopped"
    assert not env.manager._reservations
    assert not env.manager.agent_runs
    worker.agent_run.assert_not_called()
    env.deferred.cancel.assert_called_once()
    assert info.thread_future is env.future


@pytest.mark.asyncio
async def test_tracked_run_owns_identity_and_finalizes_with_redis_disabled(lifecycle, monkeypatch):
    env = lifecycle
    execution = service_tests.agent_execution
    calls = []
    run_id = "d" * 32
    env.request._track_execution = True
    env.request._projection_run_id = run_id
    monkeypatch.setattr(env.service.runtime_state_service, "enabled", False)
    monkeypatch.setattr(env.service, "track_execution", lambda identity: calls.append(("track", identity.run_id)))
    monkeypatch.setattr(env.service, "untrack_execution", lambda identity: None)
    monkeypatch.setattr(env.service, "begin_execution", lambda identity: calls.append(("begin", identity.run_id)))
    monkeypatch.setattr(
        execution, "finish_execution", lambda identity, status: calls.append(("finish", identity.run_id, status)),
    )

    async def direct(_name, function, *args, **kwargs):
        return function(*args)

    async def source(_request, **kwargs):
        assert kwargs["channel"].execution_identity.run_id == run_id
        env.channel.complete("completed")
        env.future.set_result(None)
        yield "done"

    monkeypatch.setattr(env.service, "run_blocking", direct)
    monkeypatch.setattr(execution, "run_blocking", direct)
    response = await env.start(source)
    await response.agentos_producer
    assert response.headers["run_id"] == response.headers["X-AgentOS-Run-ID"] == run_id
    assert calls == [("begin", run_id), ("track", run_id), ("finish", run_id, "completed")]
