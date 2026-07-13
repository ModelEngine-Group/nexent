import asyncio
import importlib
import sys
import types

import pytest


def _load_scheduler_with_runner_stub(monkeypatch):
    runner_module = types.ModuleType("services.agent_automation.runner")

    class _Runner:
        async def execute_task(self, task, trigger_type="SCHEDULED"):
            return {"task_id": task.get("task_id"), "status": "SUCCEEDED"}

    runner_module.agent_automation_runner = _Runner()
    monkeypatch.setitem(sys.modules, "services.agent_automation.runner", runner_module)
    sys.modules.pop("services.agent_automation.scheduler", None)
    return importlib.import_module("services.agent_automation.scheduler")


@pytest.mark.asyncio
async def test_scheduler_claims_only_available_capacity(monkeypatch):
    scheduler_module = _load_scheduler_with_runner_stub(monkeypatch)
    scheduler = scheduler_module.AgentAutomationScheduler()
    scheduler._semaphore = asyncio.Semaphore(2)
    await scheduler._semaphore.acquire()
    calls = {}

    def fake_claim_due_tasks(instance_id, batch_size, lease_seconds):
        calls["batch_size"] = batch_size
        scheduler._stop_event.set()
        return []

    monkeypatch.setattr(scheduler_module.agent_automation_db, "claim_due_tasks", fake_claim_due_tasks)

    await scheduler._loop()

    assert calls["batch_size"] == 1


@pytest.mark.asyncio
async def test_scheduler_renews_lease_while_task_is_running(monkeypatch):
    scheduler_module = _load_scheduler_with_runner_stub(monkeypatch)
    scheduler = scheduler_module.AgentAutomationScheduler()
    stop_event = asyncio.Event()
    calls = []

    monkeypatch.setattr(scheduler_module, "AGENT_AUTOMATION_LEASE_SECONDS", 0.03)

    def fake_renew(task_id, instance_id, lease_seconds):
        calls.append((task_id, instance_id, lease_seconds))
        stop_event.set()
        return True

    monkeypatch.setattr(scheduler_module.agent_automation_db, "renew_task_lock", fake_renew)

    await scheduler._renew_task_lease(42, stop_event)

    assert calls == [(42, scheduler.instance_id, 0.03)]
