# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from contracts.errors.exceptions import WorkbenchError
from management.services.automation import runner


@pytest.mark.asyncio
@pytest.mark.parametrize(("saved", "error"), [
    (False, None), (True, None), (True, "RUNTIME_SKILL_FORBIDDEN"), (True, "WORKBENCH_KNOWLEDGE_UNAVAILABLE"),
])
async def test_workbench_runner_uses_task_configuration_and_surfaces_denials(mocker, saved, error):
    conversation = {
        "workbench_config": {"mode": "generic_chat", "skill_mounts": [{"skill_id": 7}]},
        "workbench_config_version": 3,
    }
    snapshot = {"model_id": 17}
    if saved:
        snapshot[runner.agent_automation_db.WORKBENCH_EXECUTION_KEY] = {
            "config": {"mode": "generic_chat", "skill_mounts": [{"skill_id": 8}]}, "version": 2,
        }
    task = {
        "task_id": 9, "conversation_id": 12, "agent_id": 4, "user_id": "owner", "tenant_id": "tenant",
        "instruction": "Summarize", "runtime_snapshot": snapshot,
    }
    run = {**task, "run_id": 3, "runtime_run_id": "b" * 32}
    mocker.patch.object(runner, "validate_bindings_available", AsyncMock(return_value={"available": True}))
    mocker.patch.object(runner, "get_conversation", return_value=conversation)
    mocker.patch.object(runner.automation_conversation_adapter, "append_run_prompt", return_value={
        "user_message_id": 5, "assistant_message_index": 7, "history": [],
    })
    mocker.patch.object(runner.agent_automation_db, "update_run", side_effect=lambda _, data, *args, **kw: data)
    expected_skill = 8 if saved else 7

    def prepare(request, saved_conversation, user_id, tenant_id):
        assert (saved_conversation, user_id, tenant_id) == (conversation, "owner", "tenant")
        assert request.entrypoint == "workbench" and request.expected_workbench_config_version == 3
        assert request.workbench.skill_mounts[0].skill_id == expected_skill
        assert request.model_id == 17 and request.enable_automation_tool is False
        if error == "RUNTIME_SKILL_FORBIDDEN":
            raise WorkbenchError(error, status_code=403)
        from management.services.agent.workbench import PreparedWorkbench
        knowledge = SimpleNamespace(warnings=[{"code": "KNOWLEDGE_SCOPE_ITEM_UNAVAILABLE"}]) if error else None
        return PreparedWorkbench(request.workbench, None, 3, 4, knowledge=knowledge)

    executor = runner.AgentAutomationRunner()
    mocker.patch.object(runner, "prepare_portable_workbench", side_effect=prepare)
    compile_run = mocker.patch.object(runner, "prepare_conversation_snapshot", AsyncMock(
        return_value=SimpleNamespace(memory_enabled=False),
    ))
    fallback = mocker.patch.object(runner, "forward_tracked_background", AsyncMock())
    failure = mocker.patch.object(executor, "_fail_run", return_value={"status": "FAILED"})
    projection = mocker.patch.object(executor, "_project_prepared_run", AsyncMock())
    mocker.patch.object(executor, "_finish_prepared_projection", return_value={"status": "SUCCEEDED"})
    admit = AsyncMock(side_effect=lambda *args: compile_run.await_args.args[1])
    mocker.patch.object(runner, "_agentos_client", return_value=SimpleNamespace(start_prepared_run=admit))

    result = await executor._execute_active_run(run, task)

    fallback.assert_not_awaited()
    if error:
        assert result["status"] == "FAILED"
        assert failure.call_args.args[2] == error
        compile_run.assert_not_awaited()
        admit.assert_not_awaited()
    else:
        assert result["status"] == "SUCCEEDED"
        assert compile_run.await_args.kwargs["workbench"].version == (2 if saved else 3)
        assert compile_run.await_args.kwargs["current_user_message_id"] == 5
        assert run["projection_message_index"] == 7
        admit.assert_awaited_once()
        projection.assert_awaited_once()


@pytest.mark.parametrize(("problem", "error_code"), [
    ("missing_conversation", "AUTOMATION_CONVERSATION_UNAVAILABLE"),
    ("invalid_version", "WORKBENCH_CONFIG_UNAVAILABLE"),
    ("missing_workbench_config", "WORKBENCH_CONFIG_UNAVAILABLE"),
    ("invalid_config", "WORKBENCH_CONFIG_INVALID"),
    ("no_portable_config", "WORKBENCH_CONFIG_UNAVAILABLE"),
    ("no_prepared_snapshot", "WORKBENCH_CONFIG_UNAVAILABLE"),
])
async def test_unavailable_workbench_cannot_launch_an_ordinary_background_run(mocker, problem, error_code):
    from management.services.agent.workbench import PreparedWorkbench

    config = {"mode": "generic_chat"}
    conversation = {
        "workbench_config": None if problem == "missing_workbench_config" else config,
        "workbench_config_version": 3,
    }
    task = {
        "task_id": 9, "conversation_id": 12, "agent_id": 4, "user_id": "owner", "tenant_id": "tenant",
        "instruction": "Summarize",
        "runtime_snapshot": {runner.agent_automation_db.WORKBENCH_EXECUTION_KEY: {
            "version": 0 if problem == "invalid_version" else 2,
            "config": {"mode": "invalid"} if problem == "invalid_config" else config,
        }},
    }
    run = {**task, "run_id": 3, "runtime_run_id": "b" * 32}
    mocker.patch.object(runner, "validate_bindings_available", return_value={"available": True})
    mocker.patch.object(runner, "get_conversation", return_value=None if problem == "missing_conversation" else conversation)
    mocker.patch.object(runner.automation_conversation_adapter, "append_run_prompt", return_value={
        "user_message_id": 5, "assistant_message_index": 7, "history": [],
    })
    mocker.patch.object(runner.agent_automation_db, "update_run", side_effect=lambda _, data, *args, **kw: data)
    portable = mocker.patch.object(
        runner, "prepare_portable_workbench",
        side_effect=lambda request, *_: None if problem == "no_portable_config" else (
            PreparedWorkbench(request.workbench, None, 3, 4)
        ),
    )
    compile_snapshot = mocker.patch.object(runner, "prepare_conversation_snapshot", return_value=None)
    fallback = mocker.patch.object(runner, "forward_tracked_background")
    agentos = mocker.patch.object(runner, "_agentos_client")

    executor = runner.AgentAutomationRunner()
    fail_run = mocker.patch.object(executor, "_fail_run", return_value={"status": "FAILED", "error_code": error_code})

    assert await executor._execute_active_run(run, task) == {"status": "FAILED", "error_code": error_code}

    assert fail_run.call_args.args[:3] == (run, task, error_code)
    assert portable.call_count == int(problem in {"no_portable_config", "no_prepared_snapshot"})
    assert compile_snapshot.await_count == int(problem == "no_prepared_snapshot")
    fallback.assert_not_awaited()
    agentos.assert_not_called()
