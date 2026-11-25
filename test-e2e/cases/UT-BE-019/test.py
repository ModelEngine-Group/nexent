# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""D1 backend policy tests for repository, sharing, runtime and memory."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest


STAGE = pytest.mark.stage("D1")














@STAGE
@pytest.mark.case_id("UT-BE-019")
def test_automation_fifth_failure_auto_pauses_and_releases_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    from management.services.automation import runner as runner
    from contracts.automation import AutomationRunStatus

    now = datetime.now(timezone.utc)
    task = {
        "task_id": 1, "tenant_id": "t1", "user_id": "u1", "status": "ACTIVE",
        "consecutive_failures": 4, "fire_count": 1, "next_fire_at": now,
        "lock_owner": "worker", "lock_until": now + timedelta(minutes=1),
    }
    run = {
        "run_id": 2, "started_at": now, "scheduled_fire_at": now,
        "status": "RUNNING", "trigger_type": "SCHEDULED", "_lease_owner": "worker",
    }
    session = object()
    captured: dict = {}

    @contextmanager
    def task_run_transaction(task_id, tenant_id, user_id, run_id):
        assert (task_id, tenant_id, user_id, run_id) == (1, "t1", "u1", 2)
        yield session, task, run

    def update_run(run_id, values, user_id, *, expected_statuses, db_session):
        assert db_session is session
        assert (run_id, user_id, values["status"]) == (2, "u1", "FAILED")
        assert expected_statuses == ["QUEUED", "RUNNING"]
        return {**run, **values}

    def update_task(task_id, tenant_id, user_id, values, *, db_session):
        assert db_session is session
        assert (task_id, tenant_id, user_id) == (1, "t1", "u1")
        captured.update(values)

    monkeypatch.setattr(runner, "_utcnow", lambda: now)
    monkeypatch.setattr(runner.agent_automation_db, "task_run_transaction", task_run_transaction)
    monkeypatch.setattr(runner.agent_automation_db, "update_run", update_run)
    monkeypatch.setattr(runner.agent_automation_db, "update_task", update_task)
    instance = runner.AgentAutomationRunner()
    monkeypatch.setattr(instance, "_advance_scheduled_task", lambda task, now: (2, now + timedelta(hours=1), "ACTIVE"))
    instance._finish_run(run, task, AutomationRunStatus.FAILED.value, {"error_message": "boom"})
    assert captured["consecutive_failures"] == 5
    assert captured["status"] == "PAUSED_BY_SYSTEM"
    assert captured["lock_owner"] is None and captured["lock_until"] is None
