# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Tenant Workbench admission uses real registry state and the subscription path."""

import asyncio
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from contracts.agent import WorkbenchSessionConfig
from .test_agent_subscription_lifecycle import lifecycle as lifecycle


@pytest_asyncio.fixture
async def workbench(lifecycle, monkeypatch):
    env = lifecycle
    canonical = WorkbenchSessionConfig(mode="generic_chat")
    env.tenant = "tenant-a"
    env.user = "user-a"
    env.version = 1
    module = ModuleType("management.services.agent.workbench")
    module.assert_workbench_version = MagicMock()
    module.resolve_workbench_config = MagicMock(return_value=(canonical, object()))
    monkeypatch.setitem(sys.modules, "management.services.agent.workbench", module)
    monkeypatch.setattr(env.service, "ENABLE_AGENT_WORKBENCH", True)
    monkeypatch.setattr(env.service, "RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS", 50)
    monkeypatch.setattr(env.service, "_resolve_user_tenant_language", lambda **kwargs: (env.user, env.tenant, "en"))
    monkeypatch.setattr(env.service, "get_conversation_service", lambda **kwargs: {
        "conversation_id": 123, "workbench_config": canonical.model_dump(mode="json"),
        "workbench_config_version": 1,
    })

    def apply_plan(request, *_args):
        request.agent_id = 77
        request.version_no = env.version

    monkeypatch.setattr(env.service, "apply_workbench_runtime_plan", apply_plan)
    env.request.entrypoint = "workbench"
    env.request.workbench = canonical
    env.tokens = []

    def fill(tenant, count):
        tokens = [env.manager.reserve_agent_capacity(f"{tenant}:workbench_main", 50) for _ in range(count)]
        env.tokens.extend(tokens)
        return tokens

    env.fill = fill
    yield env
    for token in env.tokens:
        env.manager.release_agent_capacity(token)


async def pending_run(_request, **_kwargs):
    await asyncio.Event().wait()
    yield "unreachable"


@pytest.mark.asyncio
async def test_full_tenant_does_not_consume_another_tenants_50_slots(workbench):
    env = workbench
    env.fill("tenant-a", 50)
    with pytest.raises(env.service.RuntimeCapacityExceededError):
        await env.start(pending_run)
    env.service.runtime_thread_manager.submit.assert_not_called()

    env.tenant = "tenant-b"
    env.user = "user-b"
    env.fill("tenant-b", 49)
    response = await env.start(pending_run)
    assert env.manager.get_agent_capacity_count("tenant-a:workbench_main") == 50
    assert env.manager.get_agent_capacity_count("tenant-b:workbench_main") == 50
    assert env.manager.get_agent_capacity_count(77) == 0
    env.service.runtime_thread_manager.submit.assert_called_once()

    with pytest.raises(env.service.RuntimeCapacityExceededError):
        await env.start(pending_run)
    env.service.runtime_thread_manager.submit.assert_called_once()
    await response.body_iterator.aclose()


@pytest.mark.asyncio
async def test_users_and_versions_share_the_same_tenant_budget(workbench):
    env = workbench
    env.fill("tenant-a", 49)
    response = await env.start(pending_run)
    env.user = "another-user-in-tenant-a"
    env.version = 2
    with pytest.raises(env.service.RuntimeCapacityExceededError):
        await env.start(pending_run)
    assert env.manager.get_agent_capacity_count("tenant-a:workbench_main") == 50
    env.service.runtime_thread_manager.submit.assert_called_once()
    await response.body_iterator.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled"])
async def test_worker_terminal_state_releases_only_its_tenant_slot(workbench, outcome):
    env = workbench
    env.fill("tenant-b", 50)
    response = await env.start(pending_run)
    assert env.manager.get_agent_capacity_count("tenant-a:workbench_main") == 1
    if outcome == "cancelled":
        env.future.cancel()
    elif outcome == "failed":
        env.future.set_exception(RuntimeError("worker failed"))
    else:
        env.future.set_result(None)
    assert env.manager.get_agent_capacity_count("tenant-a:workbench_main") == 0
    assert env.manager.get_agent_capacity_count("tenant-b:workbench_main") == 50
    assert not env.manager._agent_capacity_tokens.keys() - set(env.tokens)
    await response.body_iterator.aclose()


@pytest.mark.asyncio
async def test_process_capacity_rejection_releases_workbench_slot(workbench, monkeypatch):
    env = workbench
    error = env.service.ThreadCapacityExceeded("agent-run", 200, 32)
    monkeypatch.setattr(env.service.runtime_thread_manager, "submit", MagicMock(side_effect=error))
    with pytest.raises(env.service.RuntimeCapacityExceededError):
        await env.start(pending_run)
    assert env.manager.get_agent_capacity_count("tenant-a:workbench_main") == 0
    assert not env.manager._agent_capacity_tokens


@pytest.mark.asyncio
async def test_native_agent_keeps_numeric_id_budget(lifecycle):
    env = lifecycle

    async def source(_request, **_kwargs):
        env.channel.complete()
        yield "done"

    response = await env.start(source)
    assert env.manager.get_agent_capacity_count(1) == 1
    assert env.manager.get_agent_capacity_count("t:workbench_main") == 0
    env.future.set_result(None)
    assert env.manager.get_agent_capacity_count(1) == 0
    await response.body_iterator.aclose()
