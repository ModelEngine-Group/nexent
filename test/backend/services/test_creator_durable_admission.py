# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
import json
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from redis.exceptions import RedisError

from contracts.agent import NL2AgentRunRequest, NL2SkillRunRequest
from contracts.errors.exceptions import RuntimeCapacityExceededError, RuntimeQueueTimeoutError
from management.services.agent import admission, lifecycle
from management.services.conversation import creator_execution as execution
from management.services.conversation import creator_runtime as runtime
from management.services.execution_coordination import (
    ExecutionAlreadyActiveError,
    ExecutionQuotaExceededError,
    RuntimeCoordinationUnavailableError,
)
from nexent.core.concurrency.errors import ThreadQueueTimedOut


@pytest.fixture
def creator(monkeypatch):
    worker = SimpleNamespace(execution_id="worker", future=Future())
    registry = lifecycle.AgentRunManager()
    order = []
    terminal = asyncio.Event()
    manager = SimpleNamespace(
        submit=Mock(return_value=worker),
        wait_until_started=AsyncMock(side_effect=lambda *_: order.append("worker")),
        cancel=Mock(),
    )

    def reserve(**_kwargs):
        order.append("reserve")
        return 42

    def transition(_execution_id, _owner_id, state):
        order.append(state)
        if state in {"COMPLETED", "FAILED", "STOPPED"}:
            terminal.set()
        return True

    async def redis_claim(*_args, **_kwargs):
        order.append("redis")
        return True

    async def managed(_name, function, *args, **kwargs):
        return function(*args, **kwargs)

    async def control_io(function, *args, **kwargs):
        return function(*args, **kwargs)

    state = SimpleNamespace(
        enabled=True,
        client=SimpleNamespace(ping=Mock(return_value=True)),
        _run_managed=AsyncMock(side_effect=managed),
        acquire_idempotency_async=AsyncMock(return_value=True),
        release_idempotency_async=AsyncMock(),
        claim_creator_run_async=AsyncMock(side_effect=redis_claim),
        bind_execution_message_async=AsyncMock(return_value=True),
        creator_lease_async=AsyncMock(return_value=True),
        is_cancelled_async=AsyncMock(return_value=False),
        is_execution_cancelled_async=AsyncMock(return_value=False),
        register_run=Mock(),
        mark_run_finished=Mock(),
        mark_stream_completed_async=AsyncMock(),
    )
    for module in (admission, execution, lifecycle, runtime):
        monkeypatch.setattr(module, "runtime_state_service", state)
    for module in (execution, runtime):
        monkeypatch.setattr(module, "agent_run_manager", registry)
    monkeypatch.setattr(runtime, "runtime_thread_manager", manager)
    monkeypatch.setattr(admission, "NEXENT_RECOVERY_MODE", "maintenance")
    monkeypatch.setattr(admission, "_run_coordination", control_io)
    reserve_db = Mock(side_effect=reserve)
    transition_db = Mock(side_effect=transition)
    monkeypatch.setattr(admission, "reserve_runtime_execution", reserve_db)
    monkeypatch.setattr(admission, "transition_runtime_execution", transition_db)
    monkeypatch.setattr(execution, "run_blocking", managed)
    monkeypatch.setattr(execution.system_agent_provider, "get_creator_ref", Mock(return_value=SimpleNamespace(agent_id=77)))
    monkeypatch.setattr(execution, "authorize_target", lambda target, *_: target)
    monkeypatch.setattr(execution, "get_conversation_history", Mock(return_value={
        "agent_id": 77, "message_records": [],
    }))
    monkeypatch.setattr(
        "management.services.conversation.model_preferences.read_model_preferences",
        lambda *_: {"model_parameter_preferences": {}, "selected_model_id": None},
    )
    allocate = Mock(side_effect=lambda **_: order.append("allocate") or 91)
    prepare = Mock(side_effect=lambda **_: order.append("user") or (91, 1))
    save = Mock(side_effect=lambda *_, **__: order.append("assistant") or 101)
    status = Mock()
    monkeypatch.setattr(execution, "create_creation_conversation", allocate)
    monkeypatch.setattr(execution, "prepare_creation_history", prepare)
    monkeypatch.setattr(execution, "save_message", save)
    monkeypatch.setattr(execution, "update_message_status", status)
    monkeypatch.setattr(execution, "checkpoint_creator_stream", lambda stream, **_: stream)
    channel = SimpleNamespace(
        durable_event_count=0, complete=Mock(),
        subscribe_with_history=Mock(return_value=None),
    )

    async def publish(_frame):
        channel.durable_event_count += 1

    channel.publish = AsyncMock(side_effect=publish)
    channels = SimpleNamespace(
        get_channel=Mock(return_value=None), get_or_create_channel=AsyncMock(return_value=channel),
        remove_channel=AsyncMock(),
    )
    monkeypatch.setattr(runtime, "streaming_channel_manager", channels)
    return SimpleNamespace(
        worker=worker, manager=manager, registry=registry, reserve=reserve_db, transitions=transition_db,
        state=state, allocate=allocate, prepare=prepare, save=save, status=status, channel=channel,
        terminal=terminal, order=order,
    )


def request_for(kind, *, existing=True, **kwargs):
    request_type = NL2AgentRunRequest if kind == "agent" else NL2SkillRunRequest
    return request_type(query="build", conversation_id=91 if existing else None, target={"type": kind, "id": 8}, **kwargs)


async def start(kind, request, factory):
    return await execution.start_creation_turn(
        request, kind=kind, user_id="owner", tenant_id="tenant", stream_factory=factory,
    )


async def wait_for_producer():
    if runtime._producers:
        await asyncio.wait_for(asyncio.gather(*runtime._producers), timeout=2)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["agent", "skill"])
@pytest.mark.parametrize("existing", [True, False])
async def test_claim_before_factory_and_history_with_generation_and_worker_owned_settlement(creator, kind, existing):
    async def stream():
        yield 'data: {"type":"string","content":"answer"}\n\n'

    async def factory(effective, _ref):
        creator.order.append("factory")
        control = effective._creator_control
        assert control.execution is creator.worker
        control.configure(SimpleNamespace())
        return stream()

    request = request_for(kind, existing=existing)
    _, conversation_id = await start(kind, request, factory)
    await wait_for_producer()
    assert conversation_id == 91
    assert request._creator_generation == creator.channel.generation == "execution:42"
    assert creator.registry.get_agent_run_info(91, "owner")._automation_runtime_generation == "execution:42"
    assert creator.reserve.call_args.kwargs["agent_scope"] == f"nl2{kind}_main"
    assert creator.reserve.call_args.kwargs["execution_key"] == "conversation:91"
    assert creator.reserve.call_args.kwargs["tenant_id"] == "tenant"
    assert creator.prepare.call_args.kwargs["conversation_id"] == 91
    assert creator.order == ["worker", *([] if existing else ["allocate"]), "reserve", "redis", "factory",
                             "user", "assistant", "RUNNING", "FINALIZING"]
    creator.state.claim_creator_run_async.assert_awaited_once_with("owner", 91, "execution:42", execution_id=42)
    assert creator.channel.publish.await_count > 0
    creator.state.mark_stream_completed_async.assert_awaited_once_with(
        "owner", 91, "completed", generation="execution:42", event_count=creator.channel.publish.await_count,
    )
    creator.worker.future.set_result(None)
    await asyncio.wait_for(creator.terminal.wait(), timeout=2)
    assert creator.order[-1] == "COMPLETED"
    assert creator.registry.get_agent_run_info(91, "owner") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["agent", "skill"])
@pytest.mark.parametrize("fault,expected", [
    (ExecutionAlreadyActiveError(), lifecycle.AgentRunAlreadyActiveError),
    (ExecutionQuotaExceededError(), RuntimeCapacityExceededError),
    (RuntimeCoordinationUnavailableError(), RuntimeCoordinationUnavailableError),
])
async def test_denied_reservation_leaves_stream_and_history_untouched(creator, kind, fault, expected):
    creator.reserve.side_effect = fault
    factory = AsyncMock()
    with pytest.raises(expected):
        await start(kind, request_for(kind), factory)
    creator.manager.cancel.assert_called_once()
    creator.state.claim_creator_run_async.assert_not_awaited()
    creator.allocate.assert_not_called()
    creator.prepare.assert_not_called()
    creator.save.assert_not_called()
    creator.status.assert_not_called()
    factory.assert_not_awaited()


@pytest.mark.asyncio
async def test_capacity_timeout_cannot_allocate_or_reserve(creator):
    creator.manager.wait_until_started.side_effect = ThreadQueueTimedOut("agent-run", 1)
    with pytest.raises(RuntimeQueueTimeoutError):
        await start("skill", request_for("skill", existing=False), AsyncMock())
    creator.allocate.assert_not_called()
    creator.reserve.assert_not_called()
    creator.state.claim_creator_run_async.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RedisError("unavailable"), None])
async def test_redis_fault_does_not_open_a_local_run(creator, failure):
    creator.state.claim_creator_run_async.side_effect = failure
    creator.state.enabled = failure is not None
    factory = AsyncMock()
    with pytest.raises(RuntimeCoordinationUnavailableError):
        await start("agent", request_for("agent"), factory)
    factory.assert_not_awaited()
    creator.prepare.assert_not_called()
    assert not creator.terminal.is_set()
    creator.worker.future.set_result(None)
    await asyncio.wait_for(creator.terminal.wait(), timeout=2)
    assert creator.order[-1] == "FAILED"


@pytest.mark.asyncio
@pytest.mark.parametrize("block", ["redis", "assistant"])
async def test_cancel_waits_for_in_flight_preparation_write_and_worker(creator, monkeypatch, block):
    entered = asyncio.Event()
    proceed = asyncio.Event()

    async def blocked_write():
        entered.set()
        await proceed.wait()

    if block == "redis":
        async def claim(*_args, **_kwargs):
            await blocked_write()
            return True

        creator.state.claim_creator_run_async.side_effect = claim
    else:
        async def managed(name, function, *args, **kwargs):
            if name == "creator-start-message":
                await blocked_write()
            return function(*args, **kwargs)

        monkeypatch.setattr(execution, "run_blocking", managed)

    async def stream():
        yield ""

    request = request_for("skill", request_id="retry")
    task = asyncio.create_task(start("skill", request, AsyncMock(return_value=stream())))
    await asyncio.wait_for(entered.wait(), timeout=2)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    creator.transitions.assert_not_called()
    creator.state.mark_run_finished.assert_not_called()

    proceed.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2)
    creator.state.mark_run_finished.assert_called_once_with("owner", 91, "failed", "execution:42")
    if block == "assistant":
        creator.status.assert_called_once_with(101, "failed", "owner")
        creator.state.release_idempotency_async.assert_not_awaited()
    else:
        creator.save.assert_not_called()
        creator.state.release_idempotency_async.assert_awaited_once_with("creator-request:tenant:owner:retry")
    creator.transitions.assert_not_called()
    creator.worker.future.set_result(None)
    await asyncio.wait_for(creator.terminal.wait(), timeout=2)
    assert creator.order[-1] == "STOPPED"


@pytest.mark.asyncio
async def test_handler_cancellation_after_handoff_does_not_cancel_producer(creator, monkeypatch):
    handoff = asyncio.Event()
    finish_stream = asyncio.Event()

    async def stream():
        await finish_stream.wait()
        yield 'data: {"type":"string","content":"answer"}\n\n'

    async def pause_after_launch(*args, **kwargs):
        await runtime.launch_creator(*args, **kwargs)
        handoff.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(execution, "launch_creator", pause_after_launch)
    task = asyncio.create_task(start("agent", request_for("agent"), AsyncMock(return_value=stream())))
    await asyncio.wait_for(handoff.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2)
    creator.manager.cancel.assert_not_called()
    creator.status.assert_not_called()
    assert creator.order[-1] == "RUNNING"

    finish_stream.set()
    await wait_for_producer()
    creator.channel.publish.assert_awaited_once()
    assert creator.order[-1] == "FINALIZING"
    creator.worker.future.set_result(None)
    await asyncio.wait_for(creator.terminal.wait(), timeout=2)
    assert creator.order[-1] == "COMPLETED"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["agent", "skill"])
async def test_creator_route_exposes_retryable_coordination_failure(monkeypatch, kind):
    if kind == "agent":
        from runtime.api.agent import execution as route

        endpoint = route.nl2agent_run_api
        args = {"http_request": None}
    else:
        from runtime.api.skill import creation as route

        endpoint = route.nl2skill_run_api
        args = {}
    monkeypatch.setattr(route, "get_current_user_info", Mock(return_value=("owner", "tenant", "en")))
    monkeypatch.setattr(route, "start_creation_turn", AsyncMock(side_effect=RuntimeCoordinationUnavailableError()))
    response = await endpoint(request_for(kind), authorization="test", resume=False, **args)
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    payload = json.loads(response.body)
    assert payload["code"] == "RUNTIME_COORDINATION_UNAVAILABLE"
    assert payload["retryable"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(("error", "retry_after"), [
    (RuntimeCapacityExceededError(), "1"),
    (RuntimeQueueTimeoutError(2.5), "3"),
])
async def test_skill_creator_capacity_response_keeps_body_and_retry_after(monkeypatch, error, retry_after):
    from runtime.api.skill import creation as route

    monkeypatch.setattr(route, "get_current_user_info", Mock(return_value=("owner", "tenant", "en")))
    monkeypatch.setattr(route, "start_creation_turn", AsyncMock(side_effect=error))
    response = await route.nl2skill_run_api(request_for("skill"), authorization="test", resume=False)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == retry_after
    assert json.loads(response.body) == {"message": {"code": "RUNTIME_CAPACITY_EXCEEDED", "retryable": True}}
