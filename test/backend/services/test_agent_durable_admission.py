# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from contracts.errors.exceptions import RuntimeCapacityExceededError, RuntimeUserMessagePersistenceError
from contracts.agent import AgentRequest
from management.services.agent import admission
from management.services.agent.lifecycle import AgentRunAlreadyActiveError
from management.services.execution_coordination import (
    ExecutionAlreadyActiveError,
    ExecutionQuotaExceededError,
    RuntimeCoordinationUnavailableError,
)


@pytest.fixture
def coordination(monkeypatch):
    async def managed(_lane, _spec, operation, *args, **kwargs):
        return operation(*args, **kwargs)

    database = Mock(return_value=45)
    transition = Mock(return_value=True)
    redis_state = SimpleNamespace(client=SimpleNamespace(ping=Mock(return_value=True)))
    monkeypatch.setattr(admission, "NEXENT_RECOVERY_MODE", "maintenance")
    monkeypatch.setattr(admission, "NEXENT_MAINTENANCE_EPOCH", "test-batch")
    monkeypatch.setattr(admission, "runtime_state_service", redis_state)
    monkeypatch.setattr(admission, "reserve_runtime_execution", database)
    monkeypatch.setattr(admission, "transition_runtime_execution", transition)
    monkeypatch.setattr(admission.runtime_thread_manager, "run", managed)
    request = SimpleNamespace(agent_id=12, entrypoint=None)
    return SimpleNamespace(request=request, database=database, transition=transition, redis=redis_state)


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint,scope", [(None, "agent:12"), ("workbench", "workbench_main")])
async def test_durable_admission_uses_tenant_business_key_and_waits_for_worker(coordination, entrypoint, scope):
    worker = Future()
    coordination.request.entrypoint = entrypoint
    reservation = await admission.reserve_agent_execution(coordination.request, 8, "owner", "tenant", worker)
    arguments = coordination.database.call_args.kwargs
    assert arguments["execution_key"] == "conversation:8"
    assert arguments["tenant_id"] == "tenant" and arguments["agent_scope"] == scope
    assert arguments["agent_limit"] > 0 and arguments["maintenance_epoch"] == "test-batch"
    await reservation.running()
    await reservation.finalizing()
    reservation.outcome = "completed"
    reservation.close()
    reservation.close()
    await asyncio.sleep(0)
    assert [call.args[2] for call in coordination.transition.call_args_list] == ["RUNNING", "FINALIZING"]

    worker.set_result(None)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert [call.args[2] for call in coordination.transition.call_args_list] == ["RUNNING", "FINALIZING", "COMPLETED"]
    assert all(call.args[:2] == (45, arguments["owner_instance_id"]) for call in coordination.transition.call_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("error,public_error", [
    (ExecutionAlreadyActiveError, AgentRunAlreadyActiveError),
    (ExecutionQuotaExceededError, RuntimeCapacityExceededError),
    (RuntimeCoordinationUnavailableError, RuntimeCoordinationUnavailableError),
])
async def test_durable_admission_preserves_domain_rejections(coordination, error, public_error):
    coordination.database.side_effect = error("rejected")
    with pytest.raises(public_error):
        await admission.reserve_agent_execution(coordination.request, 8, "owner", "tenant", Future())
    coordination.transition.assert_not_called()


@pytest.mark.asyncio
async def test_durable_admission_does_not_fall_back_when_redis_is_unavailable(coordination):
    coordination.redis.client.ping.side_effect = OSError("test connection loss")
    with pytest.raises(RuntimeCoordinationUnavailableError):
        await admission.reserve_agent_execution(coordination.request, 8, "owner", "tenant", Future())
    coordination.database.assert_not_called()


@pytest.mark.asyncio
async def test_cancellation_during_admission_reaps_a_late_commit(monkeypatch, coordination):
    started, proceed = asyncio.Event(), asyncio.Event()
    worker = Future()

    async def delayed(_lane, _spec, operation, *args, **kwargs):
        if operation is not coordination.transition:
            started.set()
            await proceed.wait()
        return operation(*args, **kwargs)

    monkeypatch.setattr(admission.runtime_thread_manager, "run", delayed)
    caller = asyncio.create_task(admission.reserve_agent_execution(coordination.request, 8, "owner", "tenant", worker))
    await started.wait()
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    proceed.set()
    for _ in range(4):
        await asyncio.sleep(0)
    coordination.database.assert_called_once()
    coordination.transition.assert_not_called()
    worker.set_result(None)
    for _ in range(4):
        await asyncio.sleep(0)
    assert coordination.transition.call_args.args[2] == "STOPPED"


@pytest.fixture
def agent_turn(monkeypatch, coordination):
    from management.services.agent import subscription
    from management.services.model import run_controls

    async def saved_preferences(*_args, **_kwargs):
        return {"selected_model_id": None, "model_parameter_preferences": {}}

    request = AgentRequest(agent_id=12, conversation_id=8, query="fixture")
    worker = SimpleNamespace(execution_id="manual-worker", future=Future())
    local_registry = Mock()
    monkeypatch.setattr(subscription, "_resolve_user_tenant_language", Mock(return_value=("owner", "tenant", "en")))
    monkeypatch.setattr(subscription, "get_conversation_service", Mock(return_value={"conversation_id": 8}))
    monkeypatch.setattr(subscription, "run_blocking", saved_preferences)
    monkeypatch.setattr(run_controls, "validate_agent_model_selection", Mock())
    monkeypatch.setattr(run_controls, "preflight_agent_turn_controls", Mock())
    monkeypatch.setattr(subscription, "prepare_tool_retrieval_overrides", Mock())
    monkeypatch.setattr(subscription, "agent_run_manager", local_registry)
    monkeypatch.setattr(subscription.runtime_thread_manager, "submit", Mock(return_value=worker))
    monkeypatch.setattr(subscription.runtime_thread_manager, "wait_until_started", AsyncMock())
    cancel = Mock()
    monkeypatch.setattr(subscription.runtime_thread_manager, "cancel", cancel)
    guarded_writes = ("save_messages", "update_conversation_chat_mode_service", "update_conversation_agent_id_service")
    for name in guarded_writes:
        monkeypatch.setattr(subscription, name, Mock())
    reset = AsyncMock()
    monkeypatch.setattr(subscription, "reset_agent_stream", reset)
    return SimpleNamespace(
        subscription=subscription, request=request, worker=worker, registry=local_registry,
        guarded_writes=guarded_writes, reset=reset, cancel=cancel,
    )


@pytest.mark.asyncio
async def test_rejected_manual_turn_does_not_mutate_existing_conversation(agent_turn, coordination):
    subscription = agent_turn.subscription
    coordination.database.side_effect = ExecutionAlreadyActiveError("automatic execution holds this key")

    response = await subscription.run_agent_stream(agent_turn.request, None, "owner", "tenant")
    assert response.status_code == 200 and response.headers["X-Stream-Status"] == "conflict"
    chunks = [chunk async for chunk in response.body_iterator]
    assert any('"type": "error"' in chunk for chunk in chunks)
    assert coordination.database.call_args.kwargs["execution_key"] == "conversation:8"
    for name in agent_turn.guarded_writes:
        getattr(subscription, name).assert_not_called()
    agent_turn.reset.assert_not_awaited()
    agent_turn.registry.reserve_agent_capacity.assert_not_called()
    agent_turn.registry.release_agent_run_reservation.assert_called_once()
    assert agent_turn.cancel.call_args.args == ("manual-worker",)


@pytest.mark.asyncio
@pytest.mark.parametrize("save_fails", [False, True])
async def test_northbound_persists_after_admission_on_managed_control_io(monkeypatch, agent_turn, coordination, save_fails):
    subscription = agent_turn.subscription
    save = subscription.save_messages
    stream = Mock()
    producer = AsyncMock()

    async def managed(lane, spec, operation, *args, **kwargs):
        if operation is save:
            coordination.database.assert_called_once()
            agent_turn.reset.assert_awaited_once()
            stream.assert_not_called()
            assert (lane, spec.task_name) == ("control-io", "northbound-save-user-message")
        return operation(*args, **kwargs)

    monkeypatch.setattr(subscription.runtime_thread_manager, "run", managed)
    monkeypatch.setattr(subscription, "build_agent_run_context", Mock(return_value=SimpleNamespace(metadata={}, enable_memory=False)))
    monkeypatch.setattr(subscription.streaming_channel_manager, "get_or_create_channel", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(subscription, "generate_stream", stream)
    monkeypatch.setattr(subscription, "_consume_agent_stream_producer", producer)
    if save_fails:
        save.side_effect = OSError("persistence failed")
        with pytest.raises(RuntimeUserMessagePersistenceError) as error:
            await subscription.run_agent_stream(agent_turn.request, None, "owner", "tenant")
        assert isinstance(error.value.__cause__, OSError)
        stream.assert_not_called()
        producer.assert_not_awaited()
        agent_turn.registry.release_agent_run_reservation.assert_called_once()
        agent_turn.cancel.assert_called_once()
    else:
        response = await subscription.run_agent_stream(agent_turn.request, None, "owner", "tenant")
        assert response.status_code == 200
        assert response.headers["conversation_id"] == "8"
        stream.assert_called_once()
    save.assert_called_once_with(agent_turn.request, target="user", user_id="owner", tenant_id="tenant")
    agent_turn.worker.future.set_result(None)
    for _ in range(8):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_northbound_cancellation_keeps_reservation_until_running_save_finishes(monkeypatch, agent_turn, coordination):
    subscription = agent_turn.subscription
    saving, finish_save = asyncio.Event(), asyncio.Event()

    async def managed(_lane, _spec, operation, *args, **kwargs):
        if operation is subscription.save_messages:
            saving.set()
            await finish_save.wait()
        return operation(*args, **kwargs)

    monkeypatch.setattr(subscription.runtime_thread_manager, "run", managed)
    caller = asyncio.create_task(subscription.run_agent_stream(agent_turn.request, None, "owner", "tenant"))
    await asyncio.wait_for(saving.wait(), timeout=2)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    agent_turn.worker.future.set_result(None)
    agent_turn.registry.release_agent_run_reservation.assert_not_called()
    coordination.transition.assert_not_called()
    finish_save.set()
    for _ in range(8):
        await asyncio.sleep(0)
    subscription.save_messages.assert_called_once()
    agent_turn.registry.release_agent_run_reservation.assert_called_once()
    assert coordination.transition.call_args.args[2] == "FAILED"


@pytest.mark.asyncio
async def test_rejected_automation_turn_does_not_append_prompt(monkeypatch, coordination):
    from management.services.agent import run
    from management.services.agent.background import BackgroundExecutionState

    request = AgentRequest(agent_id=12, conversation_id=8, query="fixture")
    worker = SimpleNamespace(execution_id="automatic-worker", future=Future())
    local_registry = Mock()
    monkeypatch.setattr(run, "agent_run_manager", local_registry)
    monkeypatch.setattr(run.runtime_thread_manager, "submit", Mock(return_value=worker))
    monkeypatch.setattr(run.runtime_thread_manager, "wait_until_started", AsyncMock())
    cancel = Mock()
    monkeypatch.setattr(run.runtime_thread_manager, "cancel", cancel)
    reset = AsyncMock()
    monkeypatch.setattr(run, "reset_agent_stream", reset)
    prompt = Mock()
    coordination.database.side_effect = ExecutionAlreadyActiveError("manual execution holds this key")

    with pytest.raises(AgentRunAlreadyActiveError):
        await run.run_agent_background(request, "owner", "tenant", execution_state=BackgroundExecutionState(
            runtime_generation="occurrence-32", prepare_prompt=prompt,
        ))
    assert coordination.database.call_args.kwargs["execution_key"] == "conversation:8"
    prompt.assert_not_called()
    reset.assert_not_awaited()
    local_registry.release_agent_run_reservation.assert_called_once()
    assert cancel.call_args.args == ("automatic-worker",)
