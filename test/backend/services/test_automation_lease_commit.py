# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

import pytest

from test.backend.services.test_agent_automation_runner import _base_task, _load_runner_with_stubs


@pytest.mark.parametrize("lease_current", [False, True])
def test_scheduled_completion_uses_database_lease_before_updating_either_row(monkeypatch, lease_current):
    module = _load_runner_with_stubs(monkeypatch)
    repository = module.agent_automation_db
    session = object()
    node_time = datetime(2030, 1, 2, tzinfo=timezone.utc)
    expiry = node_time + timedelta(minutes=1)
    task = {**_base_task(), "lock_owner": "scheduler-a", "lock_until": expiry.isoformat()}
    run = {"run_id": 21, "status": "RUNNING", "trigger_type": "SCHEDULED", "started_at": node_time,
           "scheduled_fire_at": task["next_fire_at"]}

    @contextmanager
    def transaction(*_args):
        yield session, task, run

    lease_check = Mock(return_value=lease_current)
    update_run = Mock(return_value={**run, "status": "SUCCEEDED"})
    update_task = Mock()
    monkeypatch.setattr(module, "_utcnow", lambda: node_time)
    monkeypatch.setattr(repository, "task_run_transaction", transaction)
    monkeypatch.setattr(repository, "lease_is_unexpired", lease_check)
    monkeypatch.setattr(repository, "update_run", update_run)
    monkeypatch.setattr(repository, "update_task", update_task)

    result = module.AgentAutomationRunner()._finish_run({**run, "_lease_owner": "scheduler-a"}, task, "SUCCEEDED", {})

    if lease_current:
        assert result["status"] == "SUCCEEDED"
        assert update_run.call_args.kwargs["db_session"] is session
        assert update_task.call_args.kwargs["db_session"] is session
    else:
        assert result == run
        update_run.assert_not_called()
        update_task.assert_not_called()
    lease_check.assert_called_once_with(session, expiry)


@pytest.mark.asyncio
async def test_scheduled_admission_refuses_an_expired_database_lease_before_creating_run(monkeypatch):
    module = _load_runner_with_stubs(monkeypatch)
    repository = module.agent_automation_db
    session = object()
    task = {**_base_task(), "lock_owner": "scheduler-a", "lock_until": "2030-01-02T00:00:00Z"}

    @contextmanager
    def transaction(*_args):
        yield session, task, None

    create_run = Mock()
    lease_check = Mock(return_value=False)
    monkeypatch.setattr(repository, "task_run_transaction", transaction)
    monkeypatch.setattr(repository, "lease_is_unexpired", lease_check)
    monkeypatch.setattr(repository, "has_active_run_for_conversation", lambda *_args: False)
    monkeypatch.setattr(repository, "create_run", create_run)

    result = await module.AgentAutomationRunner().execute_task(task, lease_owner="scheduler-a")

    assert result == {}
    create_run.assert_not_called()
    lease_check.assert_called_once_with(session, datetime(2030, 1, 2, tzinfo=timezone.utc))


@pytest.mark.asyncio
@pytest.mark.parametrize("marker,root_active,expected_reason", [
    (False, False, None),
    (True, False, "AUTOMATION_OCCURRENCE_ALREADY_STARTED"),
    (True, True, "AUTOMATION_RUN_ALREADY_ACTIVE"),
])
async def test_scheduled_admission_fences_a_previously_started_occurrence(
    monkeypatch, marker, root_active, expected_reason,
):
    module = _load_runner_with_stubs(monkeypatch)
    repository = module.agent_automation_db
    session = object()
    task = {**_base_task(), "lock_owner": "scheduler-b", "lock_until": "2030-01-02T00:00:00Z"}
    scheduled = task["next_fire_at"]
    runner = module.AgentAutomationRunner()
    execute = AsyncMock(return_value={"status": "SUCCEEDED"})
    finish = Mock(return_value={"status": "SKIPPED", "error_code": expected_reason})
    find_marker = Mock(return_value=marker)
    find_root = AsyncMock(return_value=object() if root_active else None)
    create_run = Mock(return_value={"run_id": 22})

    @contextmanager
    def transaction(*_args):
        yield session, task, None

    monkeypatch.setattr(repository, "task_run_transaction", transaction)
    monkeypatch.setattr(repository, "lease_is_unexpired", lambda *_args: True)
    monkeypatch.setattr(repository, "has_active_run_for_conversation", lambda *_args: False)
    monkeypatch.setattr(repository, "has_started_scheduled_occurrence", find_marker)
    monkeypatch.setattr(repository, "create_run", create_run)
    monkeypatch.setattr(module, "forward_active_run", find_root)
    monkeypatch.setattr(runner, "_execute_active_run", execute)
    monkeypatch.setattr(runner, "_finish_run", finish)

    result = await runner.execute_task(task, scheduled_fire_at=scheduled, lease_owner="scheduler-b")

    find_root.assert_awaited_once_with(task["conversation_id"], task["user_id"], task["tenant_id"])
    if root_active:
        find_marker.assert_not_called()
    else:
        find_marker.assert_called_once_with(session, task["task_id"], task["tenant_id"], task["user_id"], scheduled)
    assert create_run.call_args.kwargs["db_session"] is session
    run = {"run_id": 22, "_lease_owner": "scheduler-b"}
    if expected_reason is None:
        assert result == {"status": "SUCCEEDED"}
        execute.assert_awaited_once_with(run, task)
        finish.assert_not_called()
    else:
        assert result == {"status": "SKIPPED", "error_code": expected_reason}
        assert finish.call_args.args[:3] == (run, task, "SKIPPED")
        assert finish.call_args.args[3]["error_code"] == expected_reason
        execute.assert_not_called()


@pytest.mark.asyncio
async def test_scheduled_admission_does_not_execute_when_occurrence_lookup_fails(monkeypatch):
    module = _load_runner_with_stubs(monkeypatch)
    repository = module.agent_automation_db
    runner = module.AgentAutomationRunner()
    create_run = Mock()
    execute = AsyncMock()
    monkeypatch.setattr(repository, "has_active_run_for_conversation", lambda *_args: False)
    monkeypatch.setattr(
        repository, "has_started_scheduled_occurrence", Mock(side_effect=RuntimeError("database unavailable")),
    )
    monkeypatch.setattr(repository, "create_run", create_run)
    monkeypatch.setattr(runner, "_execute_active_run", execute)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await runner.execute_task(_base_task(), lease_owner="scheduler-b")

    create_run.assert_not_called()
    execute.assert_not_called()
