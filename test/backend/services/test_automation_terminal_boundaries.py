# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Terminal guards prevent stale work from changing another schedule occurrence."""

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from management.services.automation.service import AgentAutomationFacade
from test.backend.services.test_agent_automation_runner import _base_task, _load_runner_with_stubs


@pytest.fixture
def terminal(monkeypatch):
    module = _load_runner_with_stubs(monkeypatch)
    now = datetime.now(timezone.utc)
    task = {**_base_task(), "lock_owner": "scheduler", "lock_until": now + timedelta(minutes=1)}
    run = dict(run_id=77, task_id=1, status="RUNNING", trigger_type="SCHEDULED",
               scheduled_fire_at=task["next_fire_at"], started_at=now,
               user_message_id=101, assistant_message_id=102)
    session = object()
    context = SimpleNamespace(task=task, run=run)

    @contextmanager
    def transaction(*args):
        yield session, context.task, context.run

    update_task = Mock()
    update_run = Mock(side_effect=lambda run_id, values, *a, **k: {**run, **values})
    monkeypatch.setattr(module.agent_automation_db, "task_run_transaction", transaction)
    monkeypatch.setattr(module.agent_automation_db, "update_task", update_task)
    monkeypatch.setattr(module.agent_automation_db, "update_run", update_run)
    return SimpleNamespace(module=module, runner=module.AgentAutomationRunner(), context=context,
                           task=task, run=run, session=session, update_task=update_task, update_run=update_run)


@pytest.mark.parametrize("missing", ["task", "run"])
def test_missing_terminal_parent_cannot_write(monkeypatch, terminal, missing):
    fixture = terminal
    setattr(fixture.context, missing, None)
    assert fixture.runner._finish_run(fixture.run, fixture.task, "FAILED", {}) == fixture.run
    fixture.update_run.assert_not_called()
    fixture.update_task.assert_not_called()


def test_losing_terminal_compare_and_set_leaves_task_unchanged(terminal):
    fixture = terminal
    fixture.update_run.side_effect = None
    fixture.update_run.return_value = None
    assert fixture.runner._finish_run(fixture.run, fixture.task, "FAILED", {}) == fixture.run
    fixture.update_task.assert_not_called()


def test_reclaimed_schedule_cannot_finish_run_or_rewrite_task(terminal):
    fixture = terminal
    result = fixture.runner._finish_run({**fixture.run, "_lease_owner": "old-scheduler"},
                                         fixture.task, "FAILED", {})
    assert result == fixture.run
    fixture.update_run.assert_not_called()
    fixture.update_task.assert_not_called()


def test_user_cancel_returns_winner_and_preserves_bound_messages(terminal):
    fixture = terminal
    result, won = fixture.runner.cancel_run_by_user(fixture.run, fixture.task)
    assert won is True and result["status"] == "CANCELED"
    assert result["error_code"] == "AUTOMATION_RUN_CANCELED"
    assert (result["user_message_id"], result["assistant_message_id"]) == (101, 102)
    values = fixture.update_task.call_args.args[3]
    assert values["fire_count"] == 1 and values["status"] == "COMPLETED"
    assert values["consecutive_failures"] == 0
    assert values["lock_owner"] is None and values["lock_until"] is None


@pytest.mark.parametrize("status", [None, "RUNNING", "CANCELED", "SUCCEEDED"])
def test_late_terminal_write_uses_durable_current_run(monkeypatch, terminal, status):
    fixture = terminal
    fixture.context.run = {**fixture.run, "status": status} if status else None
    result = fixture.runner._finish_run(fixture.run, fixture.task, "FAILED", {})
    if status != "RUNNING":
        assert result == (fixture.context.run or fixture.run)
        fixture.update_run.assert_not_called()
        fixture.update_task.assert_not_called()
    else:
        assert result["status"] == "FAILED"


@pytest.mark.asyncio
async def test_stale_scheduled_claim_creates_no_run(monkeypatch, terminal):
    fixture = terminal
    fixture.task["lock_owner"] = "replacement"
    monkeypatch.setattr(fixture.module.agent_automation_db, "has_active_run_for_conversation", lambda *a: False)
    create = Mock()
    monkeypatch.setattr(fixture.module.agent_automation_db, "create_run", create)
    result = await fixture.runner.execute_task(fixture.task, lease_owner="old-scheduler")
    assert result == {}
    create.assert_not_called()
    fixture.update_task.assert_not_called()


@pytest.mark.asyncio
async def test_durable_user_cancel_is_a_normal_execution_result(monkeypatch, terminal):
    fixture = terminal
    canceled = {**fixture.run, "status": "CANCELED", "error_code": "AUTOMATION_RUN_CANCELED"}
    monkeypatch.setattr(fixture.module.agent_automation_db, "has_active_run_for_conversation", lambda *a: False)
    monkeypatch.setattr(fixture.module.agent_automation_db, "create_run", Mock(return_value=fixture.run))
    monkeypatch.setattr(fixture.module.agent_automation_db, "get_run", Mock(return_value=canceled))
    monkeypatch.setattr(fixture.runner, "_execute_active_run", AsyncMock(side_effect=asyncio.CancelledError()))
    stop = AsyncMock()
    monkeypatch.setattr(fixture.runner, "cancel_runtime_run", stop)
    result = await fixture.runner.execute_task(fixture.task, trigger_type="MANUAL")
    assert result == canceled
    stop.assert_not_called()
    fixture.update_run.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime_ids", [[], ["a" * 32], ["a" * 32, "b" * 32]])
async def test_conversation_stop_fences_each_runtime_execution(monkeypatch, terminal, runtime_ids):
    fixture = terminal
    monkeypatch.setattr(fixture.module.agent_automation_db, "list_active_runtime_run_ids",
                        lambda conversation, user, tenant: runtime_ids)
    stop = AsyncMock()
    monkeypatch.setattr(fixture.module, "forward_scoped_stop", stop)
    await fixture.runner.cancel_for_conversation(100, "user", "tenant")
    assert [call.args[0].run_id for call in stop.await_args_list] == runtime_ids
    assert all(call.args[0].prevent_start and call.args[0].conversation_id == 100
               and call.args[1:] == ("user", "tenant") for call in stop.await_args_list)
    delegate = AsyncMock()
    monkeypatch.setattr(fixture.module.agent_automation_runner, "cancel_for_conversation", delegate)
    await AgentAutomationFacade()._request_conversation_stop(100, "user", "tenant")
    delegate.assert_awaited_once_with(100, "user", "tenant")
