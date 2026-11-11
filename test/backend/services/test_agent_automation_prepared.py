# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from contracts.agentos import AgentRunLookup, AgentRunReference, AgentStop
from contracts.agentos import TrackedBackgroundResult
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
@pytest.mark.parametrize("memory_enabled", [False, True])
async def test_automation_records_projection_before_dispatch_and_keeps_uncertain_start(automation, mocker, memory_enabled):
    executor, run, task, client = automation
    snapshot = SimpleNamespace(memory_enabled=memory_enabled, resource=SimpleNamespace(agent_id=2))
    compile_snapshot = mocker.patch.object(runner, "prepare_conversation_snapshot", return_value=snapshot)
    legacy = mocker.patch.object(runner, "forward_tracked_background")
    writes = []

    def persist(run_id, values, user_id, *, expected_statuses, tenant_id):
        assert (run_id, user_id, tenant_id, expected_statuses) == (run["run_id"], *ACTOR, ["RUNNING"])
        writes.append(values)
        return {**run, **values}

    async def lose_ack(payload, user_id, tenant_id):
        assert payload is snapshot and (user_id, tenant_id) == ACTOR
        assert writes == [{"generated_prompt": "question", "user_message_id": 31}, {
            "projection_message_index": 9,
            "projection_memory_agent_id": 2 if memory_enabled else None,
        }]
        raise RuntimeServiceUnavailableError("lost response")

    mocker.patch.object(runner.agent_automation_db, "update_run", side_effect=persist)
    client.start_prepared_run.side_effect = lose_ack
    result = await executor._execute_active_run(run, task)
    assert result["status"] == "RUNNING" and result["projection_message_index"] == 9
    assert compile_snapshot.await_args.args[1:] == (REFERENCE, *ACTOR)
    assert compile_snapshot.await_args.kwargs["current_user_message_id"] == 31
    legacy.assert_not_awaited()


@pytest.mark.asyncio
async def test_automation_missing_projection_index_does_not_launch_legacy_run(automation, mocker):
    executor, run, task, client = automation
    runner.automation_conversation_adapter.append_run_prompt.return_value = {"user_message_id": 31, "history": []}
    compile_snapshot = mocker.patch.object(runner, "prepare_conversation_snapshot")
    legacy = mocker.patch.object(runner, "forward_tracked_background")

    with pytest.raises(KeyError, match="assistant_message_index"):
        await executor._execute_active_run(run, task)

    compile_snapshot.assert_not_awaited()
    legacy.assert_not_awaited()
    client.start_prepared_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_source_is_recorded_before_resource_compilation_failure(automation, mocker):
    executor, run, task, client = automation
    writes = []

    def persist(run_id, values, user_id, *, expected_statuses, tenant_id):
        assert (run_id, user_id, tenant_id, expected_statuses) == (run["run_id"], *ACTOR, ["RUNNING"])
        writes.append(values)
        return {**run, **values}

    async def failed_compile(request, reference, user, tenant, **kwargs):
        assert writes == [{"generated_prompt": "question", "user_message_id": 31}]
        assert reference == REFERENCE and kwargs["current_user_message_id"] == 31
        raise RuntimeServiceUnavailableError("compile interrupted")

    mocker.patch.object(runner.agent_automation_db, "update_run", side_effect=persist)
    mocker.patch.object(runner, "prepare_conversation_snapshot", side_effect=failed_compile)
    fallback = mocker.patch.object(runner, "forward_tracked_background")
    with pytest.raises(RuntimeServiceUnavailableError):
        await executor._execute_active_run(run, task)
    assert run["user_message_id"] == 31 and run["runtime_run_id"] == REFERENCE.run_id
    assert run.get("projection_message_index") is None
    fallback.assert_not_awaited()
    client.start_prepared_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_lost_source_write_stops_preparation_before_runtime(automation, mocker):
    executor, run, task, client = automation
    mocker.patch.object(runner.agent_automation_db, "update_run", return_value=None)
    current = {**run, "status": "CANCELED"}
    mocker.patch.object(runner.agent_automation_db, "get_run", return_value=current)
    compile_run = mocker.patch.object(runner, "prepare_conversation_snapshot", side_effect=AssertionError("not persisted"))
    fallback = mocker.patch.object(runner, "forward_tracked_background")
    assert await executor._execute_active_run(run, task) == current
    compile_run.assert_not_awaited()
    fallback.assert_not_awaited()
    client.start_prepared_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_preparation_retry_reuses_the_source_prompt_and_runtime_id(automation, mocker):
    executor, run, task, client = automation
    run.update(user_message_id=31, generated_prompt="original instruction")
    task["instruction"] = "edited instruction"
    append = runner.automation_conversation_adapter.append_run_prompt
    append.side_effect = AssertionError("second user message")
    load = mocker.patch.object(runner.automation_conversation_adapter, "load_run_prompt", return_value={
        "user_message_id": 31, "assistant_message_index": 9, "history": [],
    })
    mocker.patch.object(runner.agent_automation_db, "update_run", side_effect=lambda _id, values, *_args, **_kw: {**run, **values})

    async def interrupted(request, reference, user, tenant, **kwargs):
        assert request.query == "original instruction" and reference == REFERENCE
        assert kwargs["current_user_message_id"] == 31
        raise RuntimeServiceUnavailableError("interrupted again")

    mocker.patch.object(runner, "prepare_conversation_snapshot", side_effect=interrupted)
    with pytest.raises(RuntimeServiceUnavailableError):
        await executor._execute_active_run(run, task)
    load.assert_called_once_with(100, 31, "original instruction", *ACTOR)
    append.assert_not_called()
    assert runner.validate_bindings_available.await_args.kwargs["instruction"] == "original instruction"
    client.start_prepared_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_first_preparation_preserves_existing_instruction_normalization(automation, mocker):
    executor, run, task, _ = automation
    task["instruction"] = " question \n"
    mocker.patch.object(runner.agent_automation_db, "update_run", side_effect=lambda _id, values, *_args, **_kw: {**run, **values})

    async def interrupted(request, *_args, **_kwargs):
        assert request.query == "question"
        raise RuntimeServiceUnavailableError("preparation interrupted")

    mocker.patch.object(runner, "prepare_conversation_snapshot", side_effect=interrupted)
    with pytest.raises(RuntimeServiceUnavailableError):
        await executor._execute_active_run(run, task)
    assert runner.validate_bindings_available.await_args.kwargs["instruction"] == " question \n"


@pytest.mark.asyncio
@pytest.mark.parametrize("acknowledged", [False, True])
async def test_background_handoff_refreshes_projection_ownership_without_losing_lease(automation, mocker, acknowledged):
    executor, run, task, _ = automation
    run["_lease_owner"] = "scheduler-original"
    mocker.patch.object(runner.agent_automation_db, "update_run", side_effect=lambda _id, values, *_args, **_kw: {**run, **values})
    mocker.patch.object(runner, "prepare_conversation_snapshot", return_value=None)
    current = {key: value for key, value in run.items() if not key.startswith("_")}

    async def handoff(**kwargs):
        assert kwargs["run_id"] == REFERENCE.run_id
        current.update(projection_message_index=9, user_message_id=31)
        if not acknowledged:
            raise RuntimeServiceUnavailableError("reply lost")
        return TrackedBackgroundResult(**REFERENCE.model_dump(), assistant_message_id=61, chunks=3)

    mocker.patch.object(runner, "forward_tracked_background", side_effect=handoff)
    mocker.patch.object(runner.agent_automation_db, "get_run", side_effect=lambda *_: current.copy())
    finish = mocker.patch.object(executor, "_finish_prepared_projection", return_value={"status": "SUCCEEDED"})
    legacy_finish = mocker.patch.object(executor, "_finish_run", side_effect=AssertionError("unfenced task finalization"))
    if acknowledged:
        assert await executor._execute_active_run(run, task) == {"status": "SUCCEEDED"}
        finish.assert_called_once_with(run, task, ProjectedRun(61, "completed", 3))
    else:
        with pytest.raises(RuntimeServiceUnavailableError):
            await executor._execute_active_run(run, task)
        finish.assert_not_called()
    assert run["projection_message_index"] == 9 and run["_lease_owner"] == "scheduler-original"
    legacy_finish.assert_not_called()


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
@pytest.mark.parametrize("agent_id", [None, 2])
async def test_automation_projects_only_the_durable_memory_scope(automation, mocker, agent_id):
    executor, run, _, client = automation
    run.update(projection_message_index=9, projection_memory_agent_id=agent_id, user_message_id=31)
    client.resume = AsyncMock()
    mocker.patch.object(runner, "get_prepared_projection_receipt", return_value=None)
    project = mocker.patch.object(runner, "resume_assistant_projection")
    await executor._project_prepared_run(client, REFERENCE, run)
    options = project.await_args.kwargs
    assert options.get("memory_agent_id") == agent_id
    assert options.get("memory_source_message_id") == (31 if agent_id is not None else None)


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
    assert run_values["projection_memory_agent_id"] is None
    assert task_values["last_run_status"] == "CANCELED" and task_values["fire_count"] == 1


@pytest.mark.asyncio
async def test_background_refresh_failure_keeps_outcome_pending(automation, mocker):
    from sqlalchemy.exc import SQLAlchemyError

    executor, run, task, client = automation
    run["_lease_owner"] = "scheduler-original"
    mocker.patch.object(runner, "prepare_conversation_snapshot", return_value=None)
    mocker.patch.object(runner.agent_automation_db, "update_run", side_effect=lambda _id, values, *_args, **_kw: {**run, **values})
    mocker.patch.object(runner.agent_automation_db, "get_run", side_effect=SQLAlchemyError("unavailable"))
    mocker.patch.object(runner, "forward_tracked_background", return_value=TrackedBackgroundResult(
        **REFERENCE.model_dump(), assistant_message_id=55, chunks=2,
    ))
    finish = mocker.patch.object(executor, "_finish_run")
    finish_prepared = mocker.patch.object(executor, "_finish_prepared_projection")
    result = await executor._execute_active_run(run, task)
    assert result["status"] == "RUNNING" and result["_background_outcome_unknown"] is True
    assert result["_lease_owner"] == "scheduler-original"
    finish.assert_not_called()
    finish_prepared.assert_not_called()
    client.start_prepared_run.assert_not_awaited()
