# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Check tenant Workbench capacity at signed Runtime admission."""

import asyncio
from concurrent.futures import Future

import pytest

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.local_execution_registry import LocalExecutionRegistry
from nexent.core.concurrency import ThreadCapacityExceeded
from runtime.agentos import prepared_run
from runtime.executions import AgentRunConcurrencyExceededError
from ..app.test_agentos_prepared_run import ACTOR, payload, runtime


@pytest.fixture
def capacity(monkeypatch, runtime):
    monkeypatch.setattr(LocalExecutionRegistry, "_instance", None)
    registry = LocalExecutionRegistry()
    monkeypatch.setattr(prepared_run, "agent_run_manager", registry)
    monkeypatch.setattr(prepared_run, "RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS", 50)
    return registry


def fill(registry, tenant, count):
    for _ in range(count):
        registry.reserve_agent_capacity(f"{tenant}:workbench_main", 50)


def workbench(payload, **changes):
    return payload.model_copy(update={"workbench_config_version": 1, **changes})


async def join(runtime):
    await asyncio.wait_for(asyncio.gather(*list(runtime.tasks)), timeout=2)


async def pending(_info, **_options):
    await asyncio.Event().wait()
    yield "unreachable"


@pytest.mark.asyncio
async def test_full_workbench_tenant_cannot_consume_another_tenants_50_slots(monkeypatch, runtime, payload, capacity):
    monkeypatch.setattr(prepared_run, "agent_run", pending)
    fill(capacity, ACTOR.tenant_id, 50)
    with pytest.raises(AgentRunConcurrencyExceededError):
        await prepared_run.start_prepared_run(workbench(payload), ACTOR)
    runtime.begin.assert_not_called()
    runtime.prepare.assert_not_awaited()

    other = ServicePrincipal("user-b", "tenant-b")
    fill(capacity, other.tenant_id, 49)
    await prepared_run.start_prepared_run(workbench(payload), other)
    assert capacity.get_agent_capacity_count(f"{ACTOR.tenant_id}:workbench_main") == 50
    assert capacity.get_agent_capacity_count(f"{other.tenant_id}:workbench_main") == 50
    assert capacity.get_agent_capacity_count(payload.resource.agent_id) == 0

    with pytest.raises(AgentRunConcurrencyExceededError):
        await prepared_run.start_prepared_run(workbench(payload, conversation_id=43, run_id="b" * 32), other)
    runtime.begin.assert_called_once()
    runtime.stop.return_value = True
    await join(runtime)
    assert capacity.get_agent_capacity_count(f"{other.tenant_id}:workbench_main") == 49


@pytest.mark.asyncio
async def test_workbench_users_and_versions_share_the_same_tenant_budget(monkeypatch, runtime, payload, capacity):
    monkeypatch.setattr(prepared_run, "agent_run", pending)
    fill(capacity, ACTOR.tenant_id, 49)
    await prepared_run.start_prepared_run(workbench(payload), ACTOR)
    updated = workbench(
        payload, conversation_id=43, run_id="b" * 32, workbench_config_version=2,
        resource=payload.resource.model_copy(update={"version_no": 4}),
    )
    with pytest.raises(AgentRunConcurrencyExceededError):
        await prepared_run.start_prepared_run(updated, ServicePrincipal("another-owner", ACTOR.tenant_id))
    assert capacity.get_agent_capacity_count(f"{ACTOR.tenant_id}:workbench_main") == 50
    runtime.begin.assert_called_once()
    runtime.stop.return_value = True
    await join(runtime)
    assert capacity.get_agent_capacity_count(f"{ACTOR.tenant_id}:workbench_main") == 49


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["completed", "failed", "stopped"])
async def test_worker_future_releases_only_its_tenant_slot(monkeypatch, runtime, payload, capacity, outcome):
    fill(capacity, "tenant-b", 50)
    worker = Future()
    runtime.info.thread_future = worker
    runtime.info.attempt_outcome = outcome

    async def run(_info, **_options):
        yield '{"type":"final_answer","content":"test"}'

    monkeypatch.setattr(prepared_run, "agent_run", run)
    await prepared_run.start_prepared_run(workbench(payload), ACTOR)
    await join(runtime)

    key = f"{ACTOR.tenant_id}:workbench_main"
    assert capacity.get_agent_capacity_count(key) == 1
    if outcome == "completed":
        worker.set_result(None)
    elif outcome == "failed":
        worker.set_exception(RuntimeError("worker failed"))
    else:
        worker.cancel()

    assert capacity.get_agent_capacity_count(key) == 0
    assert capacity.get_agent_capacity_count("tenant-b:workbench_main") == 50
    runtime.finish.assert_called_once_with(runtime.begin.call_args.args[0], outcome)


@pytest.mark.asyncio
async def test_failed_worker_submission_releases_workbench_slot(monkeypatch, runtime, payload, capacity):
    async def run(_info, **_options):
        raise ThreadCapacityExceeded("agent-run", 200, 32)
        yield

    monkeypatch.setattr(prepared_run, "agent_run", run)
    await prepared_run.start_prepared_run(workbench(payload), ACTOR)
    await join(runtime)

    assert capacity.get_agent_capacity_count(f"{ACTOR.tenant_id}:workbench_main") == 0
    runtime.finish.assert_called_once_with(runtime.begin.call_args.args[0], "failed")


@pytest.mark.asyncio
async def test_native_agent_keeps_numeric_id_budget(monkeypatch, runtime, payload, capacity):
    monkeypatch.setattr(prepared_run, "agent_run", pending)
    await prepared_run.start_prepared_run(payload, ACTOR)

    assert capacity.get_agent_capacity_count(payload.resource.agent_id) == 1
    assert capacity.get_agent_capacity_count(f"{ACTOR.tenant_id}:workbench_main") == 0
    runtime.stop.return_value = True
    await join(runtime)
    assert capacity.get_agent_capacity_count(payload.resource.agent_id) == 0
