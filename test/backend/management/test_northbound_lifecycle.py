# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management ownership of Northbound startup, uploads and shutdown."""

import asyncio
import ast
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import APIRouter, FastAPI


@pytest.fixture
def lifecycle(monkeypatch):
    monkeypatch.setitem(sys.modules, "contracts.constants.environment",
                        SimpleNamespace(RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS=5))
    monkeypatch.setitem(sys.modules, "contracts.constants.constants",
                        SimpleNamespace(CONFIG_SERVICE_NAME="nexent-config", NORTHBOUND_SERVICE_NAME="nexent-northbound"))
    manager = MagicMock(state="created")
    manager.run = AsyncMock(side_effect=lambda lane, spec, fn: fn())
    manager.shutdown = AsyncMock()
    concurrency = SimpleNamespace(
        ManagedTaskSpec=lambda **kw: SimpleNamespace(**kw),
        ManagerState=SimpleNamespace(CREATED="created"),
        set_default_thread_manager=MagicMock(), clear_default_thread_manager=MagicMock(),
    )
    state = MagicMock()
    recovery = SimpleNamespace(recover_northbound_tasks=MagicMock(),
                               schedule_interrupted_upload_cleanup=AsyncMock())
    monkeypatch.setitem(sys.modules, "infrastructure.concurrency", SimpleNamespace(config_thread_manager=manager))
    monkeypatch.setitem(sys.modules, "nexent.core.concurrency", concurrency)
    monkeypatch.setitem(sys.modules, "infrastructure.streaming.run_state", SimpleNamespace(runtime_state_service=state))
    monkeypatch.setitem(sys.modules, "management.api.northbound", SimpleNamespace(router=APIRouter(), a2a_router=APIRouter()))
    monkeypatch.setitem(sys.modules, "infrastructure.web.app_factory", SimpleNamespace(create_app=lambda **kw: FastAPI()))
    monkeypatch.setitem(sys.modules, "management.recovery", recovery)
    path = Path(__file__).resolve().parents[3] / "backend/management/api/northbound_application.py"
    spec = importlib.util.spec_from_file_location("isolated_management_northbound", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, manager, state, concurrency, recovery


@pytest.mark.asyncio
async def test_management_owns_recovery_and_releases_cleanup_tasks(lifecycle):
    module, manager, state, concurrency, recovery = lifecycle
    tasks = []

    async def schedule(owner, *, thread_manager):
        assert thread_manager is manager
        task = asyncio.create_task(asyncio.sleep(3600))
        tasks.append(task)
        return task

    recovery.schedule_interrupted_upload_cleanup.side_effect = schedule
    async with module.northbound_lifespan(None):
        manager.start.assert_called_once_with()
        state.set_thread_manager.assert_called_once_with(manager)
        recovery.recover_northbound_tasks.assert_called_once_with()
        assert [call.args[0] for call in recovery.schedule_interrupted_upload_cleanup.await_args_list] == [
            "nexent-config", "nexent-northbound"]
        assert manager.run.await_args.args[1].owner == "management.api.northbound_application"
    assert all(task.cancelled() for task in tasks)
    manager.shutdown.assert_awaited_once_with(timeout=module.RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS)
    concurrency.clear_default_thread_manager.assert_called_once_with(manager)
    assert state.set_thread_manager.call_args.args == (None,)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["recovery", "cleanup", "body"])
async def test_startup_or_request_failure_always_closes_management_manager(lifecycle, failure):
    module, manager, state, concurrency, recovery = lifecycle
    tasks = []

    async def schedule(owner, *, thread_manager):
        if failure == "cleanup" and owner == "nexent-northbound":
            raise RuntimeError("cleanup failed")
        task = asyncio.create_task(asyncio.sleep(3600))
        tasks.append(task)
        return task

    recovery.schedule_interrupted_upload_cleanup.side_effect = schedule
    if failure == "recovery":
        recovery.recover_northbound_tasks.side_effect = RuntimeError("recovery failed")
    with pytest.raises(RuntimeError):
        async with module.northbound_lifespan(None):
            if failure == "body":
                raise RuntimeError("body failed")
            pytest.fail("Startup failure must not yield")
    assert all(task.cancelled() for task in tasks)
    manager.shutdown.assert_awaited_once()
    concurrency.clear_default_thread_manager.assert_called_once_with(manager)
    assert state.set_thread_manager.call_args.args == (None,)


def test_business_implementations_have_one_management_owner():
    backend = Path(__file__).resolve().parents[3] / "backend"
    assert (backend / "management/api/northbound.py").is_file()
    assert (backend / "management/services/northbound.py").is_file()
    assert not (backend / "gateway/api/northbound.py").exists()
    assert not (backend / "services/northbound_service.py").exists()
    tree = ast.parse((backend / "gateway/application.py").read_text(encoding="utf-8"))
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(module.startswith("management") for module in imports)
