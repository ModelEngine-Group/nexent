# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AgentOS leases are tied to actual Runtime ownership and worker completion."""

from concurrent.futures import Future
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from runtime import sandbox_runtime
from runtime.sandbox_coordination import SandboxRunBusy, SandboxCoordinationUnknown


@pytest.fixture
def coordinator(monkeypatch):
    coordinator = Mock()
    monkeypatch.setattr(sandbox_runtime, "get_coordinator", lambda: coordinator)

    async def managed(_name, execute, *, lane, owner):
        assert (lane, owner) == ("control-io", "runtime")
        return execute()

    monkeypatch.setattr(sandbox_runtime, "run_blocking", managed)
    return coordinator


async def reserve():
    return await sandbox_runtime.reserve_agentos_sandbox(
        "tenant", "user", 7, "a" * 32, kind="CHAT", cancel=None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("already_done", [False, True])
async def test_distributed_lease_survives_until_worker_done(coordinator, already_done):
    owned = await reserve()
    coordinator.activate.assert_called_once_with(owned.lease)
    worker = Future()
    if already_done:
        worker.set_result(None)
    await sandbox_runtime.release_agentos_sandbox(owned, worker)
    if not already_done:
        coordinator.finish.assert_not_called()
        worker.set_result(None)
    coordinator.finish.assert_called_once_with(owned.lease)


@pytest.mark.asyncio
async def test_activation_failure_finishes_only_its_own_lease(coordinator):
    coordinator.activate.side_effect = SandboxCoordinationUnknown("lost")
    with pytest.raises(HTTPException) as error:
        await reserve()
    assert error.value.status_code == 503
    coordinator.finish.assert_called_once_with(coordinator.reserve.return_value)


@pytest.mark.asyncio
async def test_remote_conflict_does_not_activate_or_finish_another_run(coordinator):
    coordinator.reserve.side_effect = SandboxRunBusy("active")
    with pytest.raises(HTTPException) as error:
        await reserve()
    assert error.value.status_code == 409
    coordinator.activate.assert_not_called()
    coordinator.finish.assert_not_called()
