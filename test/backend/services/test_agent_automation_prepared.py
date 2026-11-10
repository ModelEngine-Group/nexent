# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from contracts.agentos import AgentRunLookup, AgentRunReference, AgentStop
from contracts.errors.exceptions import RuntimeServiceUnavailableError, RuntimeUpstreamError
from management.services.agent.prepared_projection import ProjectedRun
from management.services.automation import runner


ACTOR = ("user", "tenant")
REFERENCE = AgentRunReference(run_id="a" * 32, conversation_id=100)


@pytest.fixture
def automation(mocker):
    run = {
        "run_id": 5, "runtime_run_id": REFERENCE.run_id, "status": "RUNNING",
        "trigger_type": "MANUAL", "conversation_id": REFERENCE.conversation_id,
        "task_id": 1, "user_id": ACTOR[0], "tenant_id": ACTOR[1],
        "started_at": datetime.now(timezone.utc),
    }
    task = {**run, "agent_id": 2, "instruction": "question", "status": "ACTIVE"}
    client = SimpleNamespace(start_prepared_run=AsyncMock(return_value=REFERENCE), inspect_run=AsyncMock())
    mocker.patch.object(runner, "_agentos_client", return_value=client)

    async def inline(_task, function, *args, lane, owner, **kwargs):
        return function(*args, **kwargs)

    mocker.patch.object(runner, "run_blocking", side_effect=inline)
    mocker.patch.object(runner, "validate_bindings_available", return_value={"available": True})
    mocker.patch.object(runner.automation_conversation_adapter, "append_run_prompt", return_value={
        "user_message_id": 31, "history": [], "assistant_message_index": 9,
    })
    return runner.AgentAutomationRunner(), run, task, client


@pytest.mark.asyncio
async def test_automation_records_projection_before_dispatch_and_keeps_uncertain_start(automation, mocker):
    executor, run, task, client = automation
    snapshot = object()
    compile_snapshot = mocker.patch.object(runner, "prepare_conversation_snapshot", return_value=snapshot)
    legacy = mocker.patch.object(runner, "forward_tracked_background")
    writes = []

    def persist(run_id, values, user_id, *, expected_statuses):
        assert run_id == run["run_id"] and user_id == ACTOR[0] and expected_statuses == ["RUNNING"]
        writes.append(values)
        return {**run, **values}

    async def lose_ack(payload, user_id, tenant_id):
        assert payload is snapshot and (user_id, tenant_id) == ACTOR
        assert writes == [{"generated_prompt": "question", "user_message_id": 31, "projection_message_index": 9}]
        raise RuntimeServiceUnavailableError("lost response")

    mocker.patch.object(runner.agent_automation_db, "update_run", side_effect=persist)
    client.start_prepared_run.side_effect = lose_ack
    result = await executor._execute_active_run(run, task)
    assert result["status"] == "RUNNING" and result["projection_message_index"] == 9
    assert compile_snapshot.await_args.args[1:] == (REFERENCE, *ACTOR)
    assert compile_snapshot.await_args.kwargs["current_user_message_id"] == 31
    legacy.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_uses_the_original_reference_and_never_dispatches(automation, mocker):
    executor, run, task, client = automation
    run["projection_message_index"] = 9
    client.inspect_run.return_value = SimpleNamespace(**REFERENCE.model_dump(), status="completed")
    mocker.patch.object(runner.agent_automation_db, "get_task", return_value=task)
    project = mocker.patch.object(executor, "_project_prepared_run", return_value=ProjectedRun(55, "completed", 2))
    finish = mocker.patch.object(executor, "_finish_prepared_projection")
    await executor.recover_prepared_run(run)
    client.inspect_run.assert_awaited_once_with(AgentRunLookup(**REFERENCE.model_dump()), *ACTOR)
    project.assert_awaited_once_with(client, REFERENCE, run)
    finish.assert_called_once_with(run, task, project.return_value)
    client.start_prepared_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_reuses_a_committed_receipt_after_journal_expiry(automation, mocker):
    executor, run, _, client = automation
    run["projection_message_index"] = 9
    client.resume = AsyncMock()
    receipt = Mock(return_value=(55, "completed"))

    mocker.patch.object(runner, "get_prepared_projection_receipt", receipt)
    result = await executor._project_prepared_run(client, REFERENCE, run)
    assert result.assistant_message_id == 55 and result.status == "completed"
    assert receipt.call_args.kwargs["message_index"] == 9
    assert receipt.call_args.kwargs["user_id"] == ACTOR[0]
    assert receipt.call_args.kwargs["tenant_id"] == ACTOR[1]
    client.resume.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_fences_missing_expired_run_before_advancing(automation, mocker):
    executor, run, task, client = automation
    run["projection_message_index"] = 9
    task["timeout_seconds"] = 5
    run["started_at"] -= timedelta(seconds=6)
    client.inspect_run.side_effect = RuntimeUpstreamError(404, b"", {})
    client.stop_run = AsyncMock(return_value=SimpleNamespace(**REFERENCE.model_dump(), status="stopped"))
    mocker.patch.object(runner.agent_automation_db, "get_task", return_value=task)
    finish = mocker.patch.object(executor, "_finish_run")
    await executor.recover_prepared_run(run)
    client.stop_run.assert_awaited_once_with(AgentStop(**REFERENCE.model_dump(), prevent_start=True), *ACTOR)
    assert finish.call_args.args[:3] == (run, task, "TIMEOUT")
    assert "projection_message_index" not in finish.call_args.args[3]
    client.start_prepared_run.assert_not_awaited()


def test_canceled_projection_preserves_status_and_advances_the_occurrence(automation, mocker):
    executor, run, task, _ = automation
    run.update(
        status="CANCELED", trigger_type="SCHEDULED", projection_message_index=9,
        finished_at=datetime.now(timezone.utc), error_message="Canceled by owner",
    )
    mocker.patch.object(executor, "_advance_scheduled_task", return_value=(1, None, "COMPLETED"))
    mocker.patch.object(runner.agent_automation_db, "get_task", return_value=task)
    finish = mocker.patch.object(runner.agent_automation_db, "finish_prepared_run", return_value=run)

    assert executor._finish_prepared_projection(run, task, ProjectedRun(55, "stopped", 2)) == run

    _, run_values, task_values = finish.call_args.args
    assert run_values["status"] == "CANCELED" and run_values["finished_at"] == run["finished_at"]
    assert run_values["assistant_message_id"] == 55 and run_values["projection_message_index"] is None
    assert task_values["last_run_status"] == "CANCELED" and task_values["fire_count"] == 1
