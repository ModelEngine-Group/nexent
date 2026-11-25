# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from contracts.errors.exceptions import (
    AgentRunAlreadyActiveError, AgentRunConcurrencyExceededError, ForbiddenError,
    RuntimeCapacityExceededError, RuntimeCoordinationUnavailableError,
)
from infrastructure.rdb.agent_execution import ActiveExecutionError, RunIdentity
from management.services.agent import admission


@pytest.fixture
def coordination(monkeypatch):
    async def managed(_lane, _spec, operation, *args, **kwargs):
        return operation(*args, **kwargs)

    database = Mock()
    running = Mock(return_value=True)
    finish = Mock(return_value=True)
    redis_state = SimpleNamespace(client=SimpleNamespace(ping=Mock(return_value=True)))
    monkeypatch.setattr(admission, "NEXENT_RECOVERY_MODE", "fixed_replicas")
    monkeypatch.setattr(admission, "runtime_state_service", redis_state)
    monkeypatch.setattr(admission, "begin_execution", database)
    monkeypatch.setattr(admission, "mark_running", running)
    monkeypatch.setattr(admission, "finish_execution", finish)
    monkeypatch.setattr(admission, "track_execution", Mock())
    monkeypatch.setattr(admission, "untrack_execution", Mock())
    monkeypatch.setattr(admission.config_thread_manager, "run", managed)
    return SimpleNamespace(database=database, running=running, finish=finish, redis=redis_state)


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["nl2agent_main", "nl2skill_main"])
async def test_durable_admission_uses_tenant_business_key_and_waits_for_worker(coordination, scope):
    worker = Future()
    reservation = await admission.reserve_agent_scope(scope, 8, "owner", "tenant", worker)
    identity, = coordination.database.call_args.args
    assert identity == RunIdentity("tenant", "owner", 8, reservation.run_id)
    assert coordination.database.call_args.kwargs["agent_scope"] == scope
    assert coordination.database.call_args.kwargs["agent_limit"] > 0
    await reservation.running()
    coordination.running.assert_called_once_with(identity, {})
    reservation.outcome = "completed"
    reservation.close()
    reservation.close()
    await asyncio.sleep(0)
    coordination.finish.assert_not_called()

    worker.set_result(None)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    coordination.finish.assert_called_once_with(identity, "completed", repair_journal=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("error,public_error", [
    (ActiveExecutionError, AgentRunAlreadyActiveError),
    (AgentRunConcurrencyExceededError, RuntimeCapacityExceededError),
    (RuntimeCoordinationUnavailableError, RuntimeCoordinationUnavailableError),
    (PermissionError, ForbiddenError),
])
async def test_durable_admission_preserves_domain_rejections(coordination, error, public_error):
    coordination.database.side_effect = error("rejected")
    with pytest.raises(public_error):
        await admission.reserve_agent_scope("nl2agent_main", 8, "owner", "tenant", Future())
    coordination.finish.assert_not_called()


@pytest.mark.asyncio
async def test_durable_admission_does_not_fall_back_when_redis_is_unavailable(coordination):
    coordination.redis.client.ping.side_effect = OSError("test connection loss")
    with pytest.raises(RuntimeCoordinationUnavailableError):
        await admission.reserve_agent_scope("nl2agent_main", 8, "owner", "tenant", Future())
    coordination.database.assert_not_called()


@pytest.mark.asyncio
async def test_cancellation_during_admission_reaps_a_late_commit(monkeypatch, coordination):
    started, proceed = asyncio.Event(), asyncio.Event()
    worker = Future()

    async def delayed(_lane, _spec, operation, *args, **kwargs):
        if operation is not coordination.finish:
            started.set()
            await proceed.wait()
        return operation(*args, **kwargs)

    monkeypatch.setattr(admission.config_thread_manager, "run", delayed)
    caller = asyncio.create_task(admission.reserve_agent_scope("nl2agent_main", 8, "owner", "tenant", worker))
    await started.wait()
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    proceed.set()
    for _ in range(4):
        await asyncio.sleep(0)
    coordination.database.assert_called_once()
    coordination.finish.assert_not_called()
    worker.set_result(None)
    for _ in range(4):
        await asyncio.sleep(0)
    assert coordination.finish.call_args.args[1] == "stopped"


@pytest.mark.asyncio
async def test_indeterminate_remote_worker_retains_the_reservation(coordination):
    coordination.redis.creator_worker_state_async = AsyncMock(return_value=None)
    reservation = await admission.reserve_agent_scope("nl2agent_main", 8, "owner", "tenant", Future())
    reservation.stream_claimed = True

    await reservation._finish()

    coordination.redis.creator_worker_state_async.assert_awaited_once_with("owner", 8, reservation.run_id, "seal")
    coordination.finish.assert_not_called()
    admission.untrack_execution.assert_called_once_with(reservation.identity)


@pytest.mark.asyncio
async def test_settlement_releases_capacity_after_remote_worker_acknowledges(coordination):
    seal = AsyncMock(side_effect=["running", "running", "closed"])
    coordination.redis.creator_worker_state_async = seal
    worker = Future()
    worker.set_result(None)
    reservation = await admission.reserve_agent_scope("nl2agent_main", 8, "owner", "tenant", worker)
    reservation.stream_claimed = True
    reservation.outcome = "stopped"

    await reservation._finish()

    assert seal.await_count == 3
    coordination.finish.assert_called_once_with(reservation.identity, "stopped", repair_journal=False)


@pytest.mark.asyncio
async def test_shutdown_stops_waiting_without_releasing_an_active_remote_worker(coordination):
    coordination.redis.creator_worker_state_async = AsyncMock(return_value="running")
    worker = Future()
    reservation = await admission.reserve_agent_scope("nl2agent_main", 8, "owner", "tenant", worker)
    reservation.stream_claimed = True
    worker.set_result(None)
    reservation.close()
    await asyncio.sleep(0)

    assert await admission.shutdown_creator_settlements(timeout=0) == 1

    coordination.finish.assert_not_called()
    admission.untrack_execution.assert_called_once_with(reservation.identity)
