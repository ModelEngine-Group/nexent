import asyncio
import importlib
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest


class _Payload:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _load_runner_with_stubs(monkeypatch):
    consts_model = types.ModuleType("consts.model")
    consts_model.AgentRequest = _Payload
    consts_model.HistoryItem = _Payload
    consts_model.MessageRequest = _Payload
    consts_model.MessageUnit = _Payload

    agent_service = types.ModuleType("services.agent_service")

    async def fail_run_agent_background(*args, **kwargs):
        raise AssertionError("Agent should not run when automation capabilities are unavailable.")

    agent_service.run_agent_background = fail_run_agent_background
    agent_service.stop_agent_tasks = lambda conversation_id, user_id: None
    agent_service.is_agent_running = lambda conversation_id, user_id: False

    conversation_service = types.ModuleType("services.conversation_management_service")
    conversation_service.get_conversation_history_service = lambda conversation_id, user_id: [{"message": []}]
    conversation_service.save_message = lambda request, user_id, tenant_id: 1
    conversation_service.save_message_unit = lambda **kwargs: None

    monkeypatch.setitem(sys.modules, "consts.model", consts_model)
    monkeypatch.setitem(sys.modules, "services.agent_service", agent_service)
    monkeypatch.setitem(sys.modules, "services.conversation_management_service", conversation_service)
    sys.modules.pop("services.agent_automation.runner", None)
    runner_module = importlib.import_module("services.agent_automation.runner")
    monkeypatch.setattr(runner_module.agent_automation_db, "get_task", lambda *args: None)
    return runner_module


def _base_task():
    return {
        "task_id": 1,
        "tenant_id": "tenant",
        "user_id": "user",
        "conversation_id": 100,
        "agent_id": 2,
        "agent_version_no": None,
        "title": "每日检索",
        "instruction": "每天检索项目动态",
        "capability_bindings": [{"type": "TOOL", "name": "search", "binding_ref": "tool:search"}],
        "next_fire_at": datetime.now(timezone.utc),
        "schedule_config": {
            "mode": "ONCE",
            "rule_type": "AT",
            "timezone": "Asia/Shanghai",
            "start_at": "2030-01-01T09:00:00+08:00",
        },
        "fire_count": 0,
        "consecutive_failures": 0,
        "status": "ACTIVE",
    }


def test_scheduled_task_state_update_is_fenced_by_lease_owner(monkeypatch):
    runner_module = _load_runner_with_stubs(monkeypatch)
    captured = {}

    def fake_update_owned(task_id, tenant_id, user_id, lock_owner, values):
        captured.update(
            task_id=task_id,
            tenant_id=tenant_id,
            user_id=user_id,
            lock_owner=lock_owner,
            values=values,
        )
        return {"task_id": task_id, **values}

    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "update_task_if_lock_owner",
        fake_update_owned,
    )
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "update_task",
        lambda *args, **kwargs: pytest.fail("scheduled state must use a fenced update"),
    )

    result = runner_module.AgentAutomationRunner()._update_task_state(
        _base_task(),
        {"status": "COMPLETED"},
        "SCHEDULED",
        "scheduler-a",
    )

    assert result["status"] == "COMPLETED"
    assert captured["lock_owner"] == "scheduler-a"


@pytest.mark.asyncio
async def test_runner_fails_without_calling_agent_when_capability_unavailable(monkeypatch):
    runner_module = _load_runner_with_stubs(monkeypatch)
    updates = {}

    async def fake_validate_bindings_available(*args, **kwargs):
        return {
            "available": False,
            "unavailable_bindings": [{"type": "TOOL", "name": "search"}],
        }

    monkeypatch.setattr(runner_module, "validate_bindings_available", fake_validate_bindings_available)
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "has_active_run_for_conversation",
        lambda conversation_id: False,
    )
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "create_run",
        lambda run_data, user_id: {
            **run_data,
            "run_id": 12,
            "started_at": datetime.now(timezone.utc),
        },
    )

    def fake_update_run(run_id, values, user_id=None, expected_statuses=None):
        updates["run"] = {"run_id": run_id, **values}
        return updates["run"]

    def fake_update_task(task_id, tenant_id, user_id, values):
        updates["task"] = {"task_id": task_id, **values}
        return updates["task"]

    monkeypatch.setattr(runner_module.agent_automation_db, "update_run", fake_update_run)
    monkeypatch.setattr(runner_module.agent_automation_db, "update_task", fake_update_task)

    run = await runner_module.AgentAutomationRunner().execute_task(_base_task())

    assert run["status"] == "FAILED"
    assert run["error_code"] == "AUTOMATION_CAPABILITY_UNAVAILABLE"
    assert updates["task"]["last_run_status"] == "FAILED"


@pytest.mark.asyncio
async def test_runner_skips_when_conversation_agent_is_running(monkeypatch):
    runner_module = _load_runner_with_stubs(monkeypatch)
    monkeypatch.setattr(runner_module, "is_agent_running", lambda conversation_id, user_id: True)
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "has_active_run_for_conversation",
        lambda conversation_id: False,
    )
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "create_run",
        lambda run_data, user_id: {
            **run_data,
            "run_id": 13,
            "started_at": datetime.now(timezone.utc),
        },
    )

    task_updates = {}

    def fake_update_task(task_id, tenant_id, user_id, values):
        task_updates.update(values)
        return {"task_id": task_id, **values}

    monkeypatch.setattr(runner_module.agent_automation_db, "update_task", fake_update_task)

    run = await runner_module.AgentAutomationRunner().execute_task(_base_task())

    assert run["status"] == "SKIPPED"
    assert run["error_code"] == "AUTOMATION_RUN_ALREADY_ACTIVE"
    assert task_updates["last_run_status"] == "SKIPPED"
    assert task_updates["fire_count"] == 1
    assert task_updates["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_runner_passes_model_and_tool_params_to_background_agent(monkeypatch):
    runner_module = _load_runner_with_stubs(monkeypatch)
    captured = {}

    async def fake_validate_bindings_available(*args, **kwargs):
        return {"available": True, "unavailable_bindings": []}

    async def fake_run_agent_background(agent_request, user_id, tenant_id, skip_user_save=False):
        captured["agent_request"] = agent_request
        captured["user_id"] = user_id
        captured["tenant_id"] = tenant_id
        captured["skip_user_save"] = skip_user_save
        return {"assistant_message_id": 456}

    monkeypatch.setattr(runner_module, "validate_bindings_available", fake_validate_bindings_available)
    monkeypatch.setattr(runner_module, "run_agent_background", fake_run_agent_background)
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "has_active_run_for_conversation",
        lambda conversation_id: False,
    )
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "create_run",
        lambda run_data, user_id: {
            **run_data,
            "run_id": 14,
            "started_at": datetime.now(timezone.utc),
        },
    )
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "update_run",
        lambda run_id, values, user_id=None, expected_statuses=None: {"run_id": run_id, **values},
    )
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "update_task",
        lambda task_id, tenant_id, user_id, values: {"task_id": task_id, **values},
    )

    task = {
        **_base_task(),
        "runtime_snapshot": {
            "model_id": 55,
            "tool_params": {"tools": {"search": {"top_k": 5}}},
        },
    }

    run = await runner_module.AgentAutomationRunner().execute_task(task)

    assert run["status"] == "SUCCEEDED"
    assert captured["agent_request"].model_id == 55
    assert captured["agent_request"].tool_params == {"tools": {"search": {"top_k": 5}}}
    assert captured["agent_request"].conversation_id == 100
    assert captured["skip_user_save"] is True


@pytest.mark.asyncio
async def test_runner_uses_confirmed_instruction_with_current_runtime_configuration(monkeypatch):
    runner_module = _load_runner_with_stubs(monkeypatch)
    captured = {}

    async def fake_validate_bindings_available(*args, **kwargs):
        return {
            "available": True,
            "unavailable_bindings": [],
            "resolution": {
                "agent_snapshot": {
                    "agent_id": 2,
                    "name": "最新周报智能体",
                    "description": "使用最新配置生成管理周报",
                    "tools_count": 2,
                },
                "matched_capabilities": [
                    {
                        "type": "TOOL",
                        "name": "latest-search",
                        "binding_ref": "tool:latest-search",
                    }
                ],
            },
        }

    async def fake_run_agent_background(agent_request, *args, **kwargs):
        captured["agent_request"] = agent_request
        return {"assistant_message_id": 456}

    monkeypatch.setattr(runner_module, "validate_bindings_available", fake_validate_bindings_available)
    monkeypatch.setattr(runner_module, "run_agent_background", fake_run_agent_background)
    monkeypatch.setattr(runner_module.agent_automation_db, "has_active_run_for_conversation", lambda _: False)
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "create_run",
        lambda values, user_id: {
            "run_id": 18,
            "started_at": datetime.now(timezone.utc),
            **values,
        },
    )
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "update_run",
        lambda run_id, values, user_id=None, expected_statuses=None: {"run_id": run_id, **values},
    )
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "update_task",
        lambda task_id, tenant_id, user_id, values: {"task_id": task_id, **values},
    )

    task = {
        **_base_task(),
        "runtime_snapshot": {
            "name": "旧周报智能体",
            "description": "旧描述",
            "model_id": 55,
            "tool_params": {"tools": {"search": {"top_k": 5}}},
            "original_instruction": "发送一份管理周报",
        },
    }

    run = await runner_module.AgentAutomationRunner().execute_task(task)

    assert run["status"] == "SUCCEEDED"
    assert captured["agent_request"].query == task["instruction"]
    assert captured["agent_request"].model_id == 55
    assert captured["agent_request"].tool_params == {"tools": {"search": {"top_k": 5}}}


@pytest.mark.asyncio
async def test_runner_enforces_task_timeout_and_stops_agent(monkeypatch):
    runner_module = _load_runner_with_stubs(monkeypatch)
    updates = {}
    stopped = {}

    async def fake_validate_bindings_available(*args, **kwargs):
        return {"available": True, "unavailable_bindings": []}

    async def slow_run_agent_background(*args, **kwargs):
        await asyncio.sleep(1)
        return {"assistant_message_id": 456}

    monkeypatch.setattr(runner_module, "validate_bindings_available", fake_validate_bindings_available)
    monkeypatch.setattr(runner_module, "run_agent_background", slow_run_agent_background)
    monkeypatch.setattr(runner_module.agent_automation_db, "has_active_run_for_conversation", lambda _: False)
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "create_run",
        lambda values, user_id: {"run_id": 15, **values},
    )
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "update_run",
        lambda run_id, values, user_id=None, expected_statuses=None: {"run_id": run_id, **values},
    )
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "update_task",
        lambda task_id, tenant_id, user_id, values: updates.setdefault("task", values),
    )
    monkeypatch.setattr(
        runner_module,
        "stop_agent_tasks",
        lambda conversation_id, user_id: stopped.update({
            "conversation_id": conversation_id,
            "user_id": user_id,
        }),
    )

    run = await runner_module.AgentAutomationRunner().execute_task({
        **_base_task(),
        "timeout_seconds": 0.01,
    })

    assert run["status"] == "TIMEOUT"
    assert run["error_code"] == "AUTOMATION_RUN_TIMEOUT"
    assert updates["task"]["last_run_status"] == "TIMEOUT"
    assert updates["task"]["consecutive_failures"] == 1
    assert stopped == {"conversation_id": 100, "user_id": "user"}


def test_finish_run_does_not_overwrite_canceled_run(monkeypatch):
    runner_module = _load_runner_with_stubs(monkeypatch)
    task_update_called = False

    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "update_run",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "get_run",
        lambda run_id, tenant_id, user_id: {"run_id": run_id, "status": "CANCELED"},
    )

    def fail_update_task(*args, **kwargs):
        nonlocal task_update_called
        task_update_called = True

    monkeypatch.setattr(runner_module.agent_automation_db, "update_task", fail_update_task)

    result = runner_module.AgentAutomationRunner()._finish_run(
        {"run_id": 16, "started_at": datetime.now(timezone.utc)},
        _base_task(),
        "SUCCEEDED",
        {},
    )

    assert result["status"] == "CANCELED"
    assert task_update_called is False


def test_finish_run_preserves_task_paused_during_execution(monkeypatch):
    runner_module = _load_runner_with_stubs(monkeypatch)
    captured = {}
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "update_run",
        lambda run_id, values, user_id=None, expected_statuses=None: {"run_id": run_id, **values},
    )
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "get_task",
        lambda *args: {"status": "PAUSED"},
    )
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "update_task",
        lambda task_id, tenant_id, user_id, values: captured.update(values),
    )

    runner_module.AgentAutomationRunner()._finish_run(
        {"run_id": 17, "started_at": datetime.now(timezone.utc)},
        _base_task(),
        "SUCCEEDED",
        {},
    )

    assert captured["status"] == "PAUSED"


def test_scheduled_failure_advances_to_next_occurrence(monkeypatch):
    runner_module = _load_runner_with_stubs(monkeypatch)
    captured = {}
    started_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "update_run",
        lambda run_id, values, user_id=None, expected_statuses=None: {"run_id": run_id, **values},
    )
    monkeypatch.setattr(runner_module.agent_automation_db, "get_task", lambda *args: None)
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "update_task",
        lambda task_id, tenant_id, user_id, values: captured.update(values),
    )
    task = {
        **_base_task(),
        "schedule_config": {
            "mode": "RECURRING",
            "rule_type": "CRON",
            "timezone": "Asia/Shanghai",
            "start_at": "2020-01-01T09:00:00+08:00",
            "cron_expr": "0 9 * * *",
        },
    }

    runner_module.AgentAutomationRunner()._finish_run(
        {"run_id": 19, "started_at": started_at, "trigger_type": "SCHEDULED"},
        task,
        "FAILED",
        {"error_message": "temporary failure"},
    )

    assert captured["fire_count"] == 1
    assert captured["next_fire_at"] > datetime.now(timezone.utc)
    assert captured["status"] == "ACTIVE"
    assert captured["consecutive_failures"] == 1


def test_manual_run_does_not_consume_scheduled_occurrence(monkeypatch):
    runner_module = _load_runner_with_stubs(monkeypatch)
    captured = {}
    initial_next_fire = datetime.now(timezone.utc) + timedelta(days=2)
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "update_run",
        lambda run_id, values, user_id=None, expected_statuses=None: {"run_id": run_id, **values},
    )
    monkeypatch.setattr(runner_module.agent_automation_db, "get_task", lambda *args: None)
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "update_task",
        lambda task_id, tenant_id, user_id, values: captured.update(values),
    )
    task = {
        **_base_task(),
        "fire_count": 4,
        "consecutive_failures": 2,
        "next_fire_at": initial_next_fire,
        "schedule_config": {
            "mode": "RECURRING",
            "rule_type": "CRON",
            "timezone": "Asia/Shanghai",
            "start_at": "2020-01-01T09:00:00+08:00",
            "cron_expr": "0 9 * * *",
        },
    }

    runner_module.AgentAutomationRunner()._finish_run(
        {
            "run_id": 20,
            "started_at": datetime.now(timezone.utc) - timedelta(seconds=1),
            "trigger_type": "MANUAL",
        },
        task,
        "SUCCEEDED",
        {},
    )

    assert captured["fire_count"] == 4
    assert captured["next_fire_at"] == initial_next_fire
    assert captured["status"] == "ACTIVE"
    assert captured["consecutive_failures"] == 2


def test_datetime_and_history_helpers_cover_fallback_inputs(monkeypatch):
    runner_module = _load_runner_with_stubs(monkeypatch)
    parsed = runner_module._parse_dt("2030-01-01T00:00:00Z")
    fallback = runner_module._parse_dt(None)

    assert parsed == datetime(2030, 1, 1, tzinfo=timezone.utc)
    assert fallback.tzinfo == timezone.utc
    assert runner_module._history_items([]) == []

    assert runner_module._message_content({
        "message": [
            {"type": "string", "content": "draft"},
            {"type": "automation_proposal", "content": "hidden"},
            {"type": "final_answer", "content": "final"},
        ]
    }) == "final"
    history = runner_module._history_items([{
        "message": [
            {
                "role": "assistant",
                "message": [
                    {"type": "string", "content": "visible"},
                    {"type": "automation_proposal", "content": "hidden"},
                ],
            },
            {"role": "user", "message": ""},
        ]
    }])
    assert [(item.role, item.content) for item in history] == [("assistant", "visible")]


@pytest.mark.asyncio
async def test_execute_task_carries_lease_owner_into_active_run(monkeypatch):
    runner_module = _load_runner_with_stubs(monkeypatch)
    runner = runner_module.AgentAutomationRunner()
    captured = {}
    monkeypatch.setattr(runner_module.agent_automation_db, "has_active_run_for_conversation", lambda _: False)
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "create_run",
        lambda values, user_id: {"run_id": 21, **values},
    )

    async def capture_active_run(run, task, scheduled, trigger_type):
        captured.update(run)
        return run

    monkeypatch.setattr(runner, "_execute_active_run", capture_active_run)

    result = await runner.execute_task(_base_task(), lease_owner="scheduler-a")

    assert result["_lease_owner"] == "scheduler-a"
    assert captured["_lease_owner"] == "scheduler-a"


@pytest.mark.asyncio
async def test_execute_task_cancels_interrupted_run_and_maps_unexpected_failure(monkeypatch):
    runner_module = _load_runner_with_stubs(monkeypatch)
    runner = runner_module.AgentAutomationRunner()
    canceled = []
    monkeypatch.setattr(runner_module.agent_automation_db, "has_active_run_for_conversation", lambda _: False)
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "create_run",
        lambda values, user_id: {"run_id": 22, **values},
    )
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "cancel_run",
        lambda *args: canceled.append(args) or {"run_id": 22, "status": "CANCELED"},
    )
    monkeypatch.setattr(runner, "cancel_for_conversation", lambda *args: canceled.append(args))

    async def interrupt(*args):
        raise asyncio.CancelledError

    monkeypatch.setattr(runner, "_execute_active_run", interrupt)
    with pytest.raises(asyncio.CancelledError):
        await runner.execute_task(_base_task())
    assert any(call and call[0] == 22 for call in canceled)

    async def fail(*args):
        raise RuntimeError("agent failed")

    monkeypatch.setattr(runner, "_execute_active_run", fail)
    monkeypatch.setattr(
        runner,
        "_fail_run",
        lambda run, task, code, message, check: {
            "status": "FAILED",
            "error_code": code,
            "error_message": message,
        },
    )
    result = await runner.execute_task(_base_task())
    assert result["error_code"] == "AUTOMATION_RUN_FAILED"
    assert result["error_message"] == "agent failed"


def test_repeated_scheduled_failures_pause_task_and_stale_writes_are_discarded(monkeypatch):
    runner_module = _load_runner_with_stubs(monkeypatch)
    runner = runner_module.AgentAutomationRunner()
    captured = {}
    task = {
        **_base_task(),
        "consecutive_failures": 4,
        "schedule_config": {
            "mode": "RECURRING",
            "rule_type": "INTERVAL",
            "timezone": "UTC",
            "start_at": "2020-01-01T00:00:00+00:00",
            "interval_seconds": 60,
        },
    }
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "update_run",
        lambda run_id, values, user_id=None, expected_statuses=None: {"run_id": run_id, **values},
    )
    monkeypatch.setattr(runner_module.agent_automation_db, "get_task", lambda *args: None)
    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "update_task",
        lambda task_id, tenant_id, user_id, values: captured.update(values) or values,
    )

    runner._finish_run(
        {"run_id": 23, "started_at": datetime.now(timezone.utc), "trigger_type": "SCHEDULED"},
        task,
        "FAILED",
        {"error_message": "fifth failure"},
    )
    assert captured["consecutive_failures"] == 5
    assert captured["status"] == "PAUSED_BY_SYSTEM"

    monkeypatch.setattr(
        runner_module.agent_automation_db,
        "update_task_if_lock_owner",
        lambda *args: None,
    )
    assert runner._update_task_state(task, {}, "SCHEDULED", "stale-owner") is None
