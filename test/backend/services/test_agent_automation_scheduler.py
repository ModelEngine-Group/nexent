import importlib
import sys
import types

import pytest

from nexent.scheduler import ClaimedJob, ExecutionLease


def _load_scheduler_with_runner_stub(monkeypatch):
    runner_module = types.ModuleType("services.agent_automation.runner")

    class _Runner:
        async def execute_task(self, task, trigger_type="SCHEDULED", lease_owner=None):
            return {
                "task_id": task.get("task_id"),
                "status": "SUCCEEDED",
                "lease_owner": lease_owner,
            }

    runner_module.agent_automation_runner = _Runner()
    monkeypatch.setitem(sys.modules, "services.agent_automation.runner", runner_module)
    sys.modules.pop("services.agent_automation.scheduler", None)
    return importlib.import_module("services.agent_automation.scheduler")


@pytest.mark.asyncio
async def test_store_recovers_orphans_before_releasing_expired_locks(monkeypatch):
    scheduler_module = _load_scheduler_with_runner_stub(monkeypatch)
    calls = []
    monkeypatch.setattr(
        scheduler_module.agent_automation_db,
        "recover_orphaned_runs",
        lambda: calls.append("recover"),
    )
    monkeypatch.setattr(
        scheduler_module.agent_automation_db,
        "release_expired_locks",
        lambda: calls.append("release"),
    )

    await scheduler_module.AgentAutomationLeaseStore().recover()

    assert calls == ["recover", "release"]


@pytest.mark.asyncio
async def test_store_claims_tasks_as_sdk_jobs(monkeypatch):
    scheduler_module = _load_scheduler_with_runner_stub(monkeypatch)
    calls = {}

    def fake_claim(owner_id, limit, lease_seconds):
        calls.update(owner_id=owner_id, limit=limit, lease_seconds=lease_seconds)
        return [{"task_id": 42, "instruction": "run"}]

    monkeypatch.setattr(scheduler_module.agent_automation_db, "claim_due_tasks", fake_claim)

    jobs = await scheduler_module.AgentAutomationLeaseStore().claim_due("scheduler-a", 2, 30)

    assert jobs == [ClaimedJob(job_id=42, payload={"task_id": 42, "instruction": "run"})]
    assert calls == {"owner_id": "scheduler-a", "limit": 2, "lease_seconds": 30}


@pytest.mark.asyncio
async def test_executor_passes_lease_owner_as_fencing_token(monkeypatch):
    scheduler_module = _load_scheduler_with_runner_stub(monkeypatch)
    captured = {}

    async def fake_execute(task, trigger_type="SCHEDULED", lease_owner=None):
        captured.update(task=task, trigger_type=trigger_type, lease_owner=lease_owner)

    monkeypatch.setattr(scheduler_module.agent_automation_runner, "execute_task", fake_execute)
    job = ClaimedJob(job_id=42, payload={"task_id": 42})
    lease = ExecutionLease(job_id=42, owner_id="scheduler-a")

    await scheduler_module.execute_agent_automation(job, lease)

    assert captured == {
        "task": {"task_id": 42},
        "trigger_type": "SCHEDULED",
        "lease_owner": "scheduler-a",
    }
