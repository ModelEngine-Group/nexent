# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Caller-owned transaction boundary for isolated automation runner units."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone


def stub_runner_transactions(monkeypatch, module):
    context = {}
    original_finish = module.AgentAutomationRunner._finish_run
    original_execute = module.AgentAutomationRunner.execute_task
    monkeypatch.setattr(module.agent_automation_db, "get_run", lambda *a: None)

    def finish(self, run, task, *args, **kwargs):
        context.update(task=task, run=run)
        return original_finish(self, run, task, *args, **kwargs)

    async def execute(self, task, *args, **kwargs):
        context.update(task=task, run=None, lease_owner=kwargs.get("lease_owner"))
        return await original_execute(self, task, *args, **kwargs)

    @contextmanager
    def transaction(task_id, tenant_id, user_id, run_id=None):
        task = dict(context["task"])
        task.update(module.agent_automation_db.get_task(task_id, tenant_id, user_id) or {})
        if context.get("lease_owner"):
            task.update(lock_owner=context["lease_owner"], lock_until=datetime.now(timezone.utc)+timedelta(minutes=1))
        run = context.get("run")
        if run is not None:
            run = {"status": "RUNNING", "trigger_type": "SCHEDULED",
                   "scheduled_fire_at": task["next_fire_at"], **run}
            run.update(module.agent_automation_db.get_run(run_id, tenant_id, user_id) or {})
        yield None, task, run

    monkeypatch.setattr(module.AgentAutomationRunner, "_finish_run", finish)
    monkeypatch.setattr(module.AgentAutomationRunner, "execute_task", execute)
    monkeypatch.setattr(module.agent_automation_db, "task_run_transaction", transaction)
