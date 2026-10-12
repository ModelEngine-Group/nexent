"""D1 backend policy tests for repository, sharing, runtime and memory."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


STAGE = pytest.mark.stage("D1")














@STAGE
@pytest.mark.case_id("UT-BE-019")
def test_automation_fifth_failure_auto_pauses_and_releases_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.agent_automation import runner
    from services.agent_automation.models import AutomationRunStatus

    now = datetime.now(timezone.utc)
    task = {
        "task_id": 1, "tenant_id": "t1", "user_id": "u1", "status": "ACTIVE",
        "consecutive_failures": 4, "fire_count": 1, "next_fire_at": now,
    }
    run = {"run_id": 2, "started_at": now, "trigger_type": "SCHEDULED", "_lease_owner": "worker"}
    monkeypatch.setattr(runner.agent_automation_db, "update_run", lambda *a, **k: {"run_id": 2})
    monkeypatch.setattr(runner.agent_automation_db, "get_task", lambda *a, **k: task)
    instance = object.__new__(runner.AgentAutomationRunner)
    monkeypatch.setattr(instance, "_advance_scheduled_task", lambda task, now: (2, now, "ACTIVE"))
    captured: dict = {}
    monkeypatch.setattr(instance, "_update_task_state", lambda task, values, trigger, owner: captured.update(values))
    instance._finish_run(run, task, AutomationRunStatus.FAILED.value, {"error_message": "boom"})
    assert captured["consecutive_failures"] == 5
    assert captured["status"] == "PAUSED_BY_SYSTEM"
    assert captured["lock_owner"] is None and captured["lock_until"] is None












