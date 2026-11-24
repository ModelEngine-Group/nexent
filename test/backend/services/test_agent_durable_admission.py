# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from contracts.errors.exceptions import AgentRunAlreadyActiveError, RuntimeCapacityExceededError
from management.services.agent import admission
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
    monkeypatch.setattr(admission.config_thread_manager, "run", managed)
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

    monkeypatch.setattr(admission.config_thread_manager, "run", delayed)
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
