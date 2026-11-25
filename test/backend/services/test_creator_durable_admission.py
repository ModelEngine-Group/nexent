# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
import json
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from redis.exceptions import RedisError

from contracts.agent import NL2AgentRunRequest, NL2SkillRunRequest
from contracts.errors.exceptions import (
    AgentRunAlreadyActiveError, AgentRunConcurrencyExceededError, RuntimeCapacityExceededError,
    RuntimeCoordinationUnavailableError, RuntimeQueueTimeoutError,
)
from infrastructure import agent_stream_channels
from infrastructure.rdb.agent_execution import ActiveExecutionError, RunIdentity
from management.services.agent import admission, control
from management.services.conversation import creator_execution as execution
from management.services.conversation import creator_runtime as runtime


@pytest.fixture
def creator(monkeypatch):
    worker = SimpleNamespace(execution_id="worker", future=Future())
    registry = runtime.CreatorExecutionRegistry()
    order = []
    terminal = asyncio.Event()
    remote_done = asyncio.Event()
    manager = SimpleNamespace(
        submit=Mock(return_value=worker),
        wait_until_started=AsyncMock(side_effect=lambda *_: order.append("worker")),
        cancel=Mock(),
    )

    def reserve(_identity, **_kwargs):
        order.append("reserve")

    def running(_identity, _versions):
        order.append("running")
        return True

    def finish(_identity, state, *, repair_journal):
        assert repair_journal is False
        order.append(state)
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
        creator_worker_state_async=AsyncMock(side_effect=lambda *args: "closed" if remote_done.is_set() else "running"),
        creator_lease_async=AsyncMock(return_value=True),
        is_cancelled_async=AsyncMock(return_value=False),
        is_execution_cancelled_async=AsyncMock(return_value=False),
        register_run=Mock(),
        mark_run_finished=Mock(),
        append_stream_event_async=AsyncMock(return_value="1-0"),
        mark_stream_completed_async=AsyncMock(),
    )
    for module in (admission, control, execution, runtime):
        monkeypatch.setattr(module, "runtime_state_service", state)
    for module in (execution, runtime):
        monkeypatch.setattr(module, "agent_run_manager", registry)
    monkeypatch.setattr(runtime, "runtime_thread_manager", manager)
    monkeypatch.setattr(admission, "NEXENT_RECOVERY_MODE", "fixed_replicas")
    monkeypatch.setattr(admission, "_run_coordination", control_io)
    reserve_db = Mock(side_effect=reserve)
    terminal_db = Mock(side_effect=finish)
    monkeypatch.setattr(admission, "begin_execution", reserve_db)
    monkeypatch.setattr(admission, "mark_running", running)
    monkeypatch.setattr(admission, "finish_execution", terminal_db)
    monkeypatch.setattr(admission, "track_execution", Mock())
    monkeypatch.setattr(admission, "untrack_execution", Mock())
    monkeypatch.setattr(execution, "run_blocking", managed)
    monkeypatch.setattr(execution.system_agent_provider, "get_creator_ref", Mock(return_value=SimpleNamespace(agent_id=77)))
    monkeypatch.setattr(execution, "authorize_target", lambda target, *_: target)
    monkeypatch.setattr(execution, "get_conversation_history", Mock(return_value={
        "agent_id": 77, "message_records": [],
    }))
    monkeypatch.setattr(execution, "get_conversation_service", Mock(return_value={"conversation_id": 91}))
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
    monkeypatch.setattr(agent_stream_channels, "creator_runtime_state_service", state)
    channel = agent_stream_channels.StreamingChannel(91, "owner")
    channel.publish = AsyncMock(wraps=channel.publish)
    channels = SimpleNamespace(
        get_channel=Mock(return_value=None), get_or_create_channel=AsyncMock(return_value=channel),
        remove_channel=AsyncMock(),
    )
    monkeypatch.setattr(runtime, "streaming_channel_manager", channels)
    return SimpleNamespace(
        worker=worker, manager=manager, registry=registry, reserve=reserve_db, transitions=terminal_db,
        state=state, allocate=allocate, prepare=prepare, save=save, status=status, channel=channel,
        terminal=terminal, remote_done=remote_done, order=order,
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
@pytest.mark.parametrize("legacy", [False, True])
async def test_replay_authenticates_creator_and_reads_exact_generation(creator, monkeypatch, legacy):
    run_id = 42 if legacy else "a" * 32
    generation = "execution:42" if legacy else run_id
    owned = AsyncMock(return_value=None if legacy else (run_id, "completed", "nl2agent_main"))
    creator.state.get_run_state_async = AsyncMock(return_value={"generation": generation})
    snapshot = {"generation": generation, "terminal_status": "completed", "message_id": 101}
    creator.state.read_execution_stream_async = AsyncMock(return_value=snapshot)
    execution.get_conversation_history.return_value["target"] = {"type": "agent", "id": 8}
    monkeypatch.setattr(execution, "get_owned_execution", owned)
    replay = Mock()
    monkeypatch.setattr(execution, "resume_owned_creator", replay)
    monkeypatch.setattr(execution, "adapt_nexent_stream", lambda stream: stream)
    request = request_for("agent", resume_message_id=101)

    _, conversation_id = await start("agent", request, AsyncMock())

    assert conversation_id == 91 and request._creator_generation == generation
    assert all(call.kwargs["agent_scope"] == "nl2agent_main" for call in owned.await_args_list)
    creator.state.read_execution_stream_async.assert_awaited_once_with("owner", 91, run_id)
    replay.assert_called_once_with(91, "owner", "tenant", run_id, snapshot, 101, agent_scope="nl2agent_main")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["agent", "skill"])
@pytest.mark.parametrize("existing", [True, False])
async def test_claim_before_factory_and_history_with_generation_and_worker_owned_settlement(creator, kind, existing):
    async def stream():
        yield 'data: {"type":"string","content":"answer"}\n\n'

    async def factory(effective, _ref):
        creator.order.append("factory")
        assert effective._creator_run_id == effective._creator_control.generation
        return stream()

    request = request_for(kind, existing=existing)
    _, conversation_id = await start(kind, request, factory)
    await wait_for_producer()
    assert conversation_id == 91
    run_id = request._creator_generation
    assert run_id == creator.channel.generation == UUID(run_id).hex
    assert creator.reserve.call_args.kwargs["agent_scope"] == f"nl2{kind}_main"
    assert creator.reserve.call_args.args == (RunIdentity("tenant", "owner", 91, run_id),)
    assert creator.save.call_args.kwargs["execution_identity"] == creator.reserve.call_args.args[0]
    assert creator.prepare.call_args.kwargs["conversation_id"] == 91
    assert creator.order == [*([] if existing else ["allocate"]), "reserve", "redis", "factory",
                             "user", "assistant", "running"]
    creator.state.claim_creator_run_async.assert_awaited_once_with("owner", 91, run_id, execution_id=run_id)
    event_count = creator.channel.publish.await_count
    assert event_count > 0
    writes = creator.state.append_stream_event_async.await_args_list
    assert [call.kwargs["generation"] for call in writes] == [run_id] * event_count
    assert [call.kwargs["replay_update"]["sequence"] for call in writes] == list(range(1, event_count + 1))
    creator.state.mark_stream_completed_async.assert_awaited_once_with(
        "owner", 91, "completed", generation=run_id, event_count=event_count,
    )
    assert not creator.terminal.is_set()
    creator.remote_done.set()
    await asyncio.wait_for(creator.terminal.wait(), timeout=2)
    assert creator.order[-1] == "completed"
    creator.transitions.assert_called_once_with(RunIdentity("tenant", "owner", 91, run_id), "completed", repair_journal=False)
    assert creator.registry.get_agent_run_info(91, "owner") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["agent", "skill"])
@pytest.mark.parametrize("fault,expected", [
    (ActiveExecutionError(), AgentRunAlreadyActiveError),
    (AgentRunConcurrencyExceededError(), RuntimeCapacityExceededError),
    (RuntimeCoordinationUnavailableError(), RuntimeCoordinationUnavailableError),
])
async def test_denied_reservation_leaves_stream_and_history_untouched(creator, kind, fault, expected):
    creator.reserve.side_effect = fault
    factory = AsyncMock()
    with pytest.raises(expected):
        await start(kind, request_for(kind), factory)
    creator.manager.cancel.assert_not_called()
    creator.state.claim_creator_run_async.assert_not_awaited()
    creator.allocate.assert_not_called()
    creator.prepare.assert_not_called()
    creator.save.assert_not_called()
    creator.status.assert_not_called()
    factory.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RedisError("unavailable"), None])
async def test_redis_fault_does_not_open_a_local_run(creator, failure):
    creator.state.claim_creator_run_async.side_effect = failure
    if failure is None:
        creator.state.client.ping.side_effect = RedisError("unavailable")
    factory = AsyncMock()
    with pytest.raises(RuntimeCoordinationUnavailableError):
        await start("agent", request_for("agent"), factory)
    factory.assert_not_awaited()
    creator.prepare.assert_not_called()
    if failure is not None:
        await asyncio.wait_for(creator.terminal.wait(), timeout=2)
        assert creator.order[-1] == "failed"
    else:
        creator.reserve.assert_not_called()


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
    creator.state.mark_run_finished.assert_called_once_with("owner", 91, "failed", creator.reserve.call_args.args[0].run_id)
    if block == "assistant":
        creator.status.assert_called_once_with(101, "failed", "owner")
        creator.state.release_idempotency_async.assert_not_awaited()
    else:
        creator.save.assert_not_called()
        creator.state.release_idempotency_async.assert_awaited_once_with("creator-request:tenant:owner:retry")
    creator.transitions.assert_not_called()
    creator.remote_done.set()
    await asyncio.wait_for(creator.terminal.wait(), timeout=2)
    assert creator.order[-1] == "stopped"


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
    assert creator.order[-1] == "running"

    finish_stream.set()
    await wait_for_producer()
    creator.channel.publish.assert_awaited_once()
    assert creator.order[-1] == "running"
    creator.remote_done.set()
    await asyncio.wait_for(creator.terminal.wait(), timeout=2)
    assert creator.order[-1] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["agent", "skill"])
async def test_creator_route_exposes_retryable_coordination_failure(monkeypatch, kind):
    if kind == "agent":
        from management.api.agent import creator as route

        endpoint = route.nl2agent_run_api
        args = {"http_request": None}
    else:
        from management.api.skill import creation as route

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
    from management.api.skill import creation as route

    monkeypatch.setattr(route, "get_current_user_info", Mock(return_value=("owner", "tenant", "en")))
    monkeypatch.setattr(route, "start_creation_turn", AsyncMock(side_effect=error))
    response = await route.nl2skill_run_api(request_for("skill"), authorization="test", resume=False)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == retry_after
    assert json.loads(response.body) == {"message": {"code": "RUNTIME_CAPACITY_EXCEEDED", "retryable": True}}
