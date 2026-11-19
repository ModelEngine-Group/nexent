# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Reconcile retained scheduled executions with their owned Runtime receipts."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from contracts.agentos import AgentRunReference, AgentRunState, AgentStop
from contracts.conversation import MessageSource
from contracts.errors.exceptions import RuntimeServiceUnavailableError, RuntimeUpstreamError
from management.services.automation import runner

REF = AgentRunReference(conversation_id=42, run_id="a" * 32)
ACTOR = "actor"
TENANT = "tenant"


@pytest.fixture
def setup(mocker):
    now = datetime(2026, 11, 19, 1, tzinfo=timezone.utc)
    mocker.patch.object(runner, "_utcnow", return_value=now)

    async def inline(_task, callback, *args, lane, owner, **kwargs):
        assert (lane, owner) == ("control-io", "management")
        return callback(*args, **kwargs)

    mocker.patch.object(runner, "run_blocking", side_effect=inline)
    active = {"run_id": 9, "runtime_run_id": REF.run_id, "conversation_id": 42, "user_id": ACTOR,
              "tenant_id": TENANT, "task_id": 6, "status": "RUNNING", "started_at": now,
              "projection_message_index": 3, "projection_memory_agent_id": 7, "user_message_id": 25}
    task = {"task_id": 6, "timeout_seconds": 120}
    read_task = mocker.patch.object(runner.agent_automation_db, "get_task", return_value=task)
    client = SimpleNamespace(inspect_run=AsyncMock(), stop_run=AsyncMock(), resume=AsyncMock())
    mocker.patch.object(runner, "_agentos_client", return_value=client)
    recovery = runner.AgentAutomationRunner()
    finish = mocker.patch.object(recovery, "_finish_run")
    finish_projection = mocker.patch.object(recovery, "_finish_prepared_projection")
    return SimpleNamespace(now=now, active=active, task=task, read_task=read_task, client=client,
                           service=recovery, finish=finish, finish_projection=finish_projection)


def state(status, **changes):
    return AgentRunState.model_validate({
        **REF.model_dump(), "status": status, "latest_event_id": None, "cancellation_requested": False, **changes,
    })


@pytest.mark.parametrize("case", ["local", "no-task", "running", "inspect-unavailable", "foreign"])
async def test_recovery_never_projects_without_a_terminal_owned_run(setup, case):
    if case == "local":
        setup.service._local_runs.add(setup.active["run_id"])
    elif case == "no-task":
        setup.read_task.return_value = None
    elif case == "inspect-unavailable":
        setup.client.inspect_run.side_effect = RuntimeUpstreamError(503, b"", {})
    elif case == "foreign":
        setup.client.inspect_run.return_value = state("completed", conversation_id=43)
    else:
        setup.client.inspect_run.return_value = state("running")

    if case in {"inspect-unavailable", "foreign"}:
        error = RuntimeUpstreamError if case == "inspect-unavailable" else RuntimeServiceUnavailableError
        with pytest.raises(error):
            await setup.service.recover_prepared_run(setup.active)
    else:
        await setup.service.recover_prepared_run(setup.active)
    if case in {"local", "no-task"}:
        setup.client.inspect_run.assert_not_awaited()
    setup.client.stop_run.assert_not_awaited()
    setup.finish_projection.assert_not_called()
    setup.finish.assert_not_called()


@pytest.mark.parametrize("stop_error", [404, 503, None])
async def test_expired_recovery_fences_before_recording_timeout(setup, stop_error):
    setup.active["started_at"] = setup.now - timedelta(minutes=5)
    setup.client.inspect_run.side_effect = RuntimeUpstreamError(404, b"", {})
    setup.client.stop_run.return_value = state("stopped")
    if stop_error:
        setup.client.stop_run.side_effect = RuntimeUpstreamError(stop_error, b"", {})

    if stop_error == 503:
        with pytest.raises(RuntimeUpstreamError, match="HTTP 503"):
            await setup.service.recover_prepared_run(setup.active)
        setup.finish.assert_not_called()
    else:
        await setup.service.recover_prepared_run(setup.active)
        setup.finish.assert_called_once_with(
            setup.active, setup.task, "TIMEOUT",
            {"error_code": "AUTOMATION_RUN_TIMEOUT", "error_message": "Automation run exceeded 120.0 seconds."},
        )
    setup.client.stop_run.assert_awaited_once_with(
        AgentStop(**REF.model_dump(), prevent_start=True), ACTOR, TENANT,
    )
    setup.finish_projection.assert_not_called()


@pytest.mark.parametrize("outcome", ["receipt", "project", "expired", "unavailable"])
async def test_terminal_recovery_reuses_receipt_or_projects_the_original_prompt(setup, mocker, outcome):
    setup.client.inspect_run.return_value = state("completed")
    receipt = mocker.patch.object(
        runner, "get_prepared_projection_receipt", return_value=(61, "completed") if outcome == "receipt" else None,
    )
    projected = runner.ProjectedRun(61, "completed", 2)
    resume = mocker.patch.object(runner, "resume_assistant_projection", return_value=projected)
    if outcome in {"expired", "unavailable"}:
        resume.side_effect = RuntimeUpstreamError(410 if outcome == "expired" else 503, b"", {})

    if outcome == "unavailable":
        with pytest.raises(RuntimeUpstreamError, match="HTTP 503"):
            await setup.service.recover_prepared_run(setup.active)
        setup.finish_projection.assert_not_called()
    else:
        await setup.service.recover_prepared_run(setup.active)
        expected = None if outcome == "expired" else (
            runner.ProjectedRun(61, "completed", 0) if outcome == "receipt" else projected
        )
        setup.finish_projection.assert_called_once_with(setup.active, setup.task, expected)
    receipt.assert_called_once_with(
        projection_run_id=REF.run_id, conversation_id=42, message_index=3,
        message_source=MessageSource.AUTOMATION, user_id=ACTOR, tenant_id=TENANT,
    )
    if outcome == "receipt":
        resume.assert_not_awaited()
    else:
        resume.assert_awaited_once_with(
            setup.client.resume, REF, ACTOR, TENANT, message_index=3, message_source=MessageSource.AUTOMATION,
            memory_agent_id=7, memory_source_message_id=25,
        )


@pytest.mark.parametrize("kind", ["canceled", "repeated-failure", "scheduled-success", "pause-race", "stale-receipt"])
def test_final_projection_preserves_terminal_state_and_concurrent_task_pause(mocker, kind):
    now = datetime(2026, 11, 19, 1, tzinfo=timezone.utc)
    mocker.patch.object(runner, "_utcnow", return_value=now)
    active = {
        "run_id": 9, "task_id": 6, "user_id": ACTOR, "tenant_id": TENANT, "trigger_type": "SCHEDULED",
        "status": "CANCELED" if kind == "canceled" else "RUNNING",
        "started_at": now - timedelta(seconds=20), "finished_at": now - timedelta(seconds=10),
        "projection_message_index": 3,
    }
    task = {"task_id": 6, "user_id": ACTOR, "tenant_id": TENANT, "status": "ACTIVE",
            "fire_count": 3, "consecutive_failures": 4, "next_fire_at": now}
    recovered = {"run_id": 9, "status": "FAILED"} if kind == "stale-receipt" else None
    read = mocker.patch.object(runner.agent_automation_db, "get_run", return_value=recovered)
    mocker.patch.object(runner.agent_automation_db, "get_task", return_value={
        **task, "status": "PAUSED" if kind == "pause-race" else "ACTIVE",
    })
    finish = mocker.patch.object(
        runner.agent_automation_db, "finish_prepared_run",
        side_effect=lambda run, values, task_values: None if recovered else values,
    )
    service = runner.AgentAutomationRunner()
    mocker.patch.object(service, "_advance_scheduled_task", return_value=(4, now + timedelta(hours=1), "ACTIVE"))
    status = {"canceled": "CANCELED", "repeated-failure": "FAILED", "stale-receipt": "FAILED"}.get(kind, "SUCCEEDED")

    result = service._finish_prepared_run_state(active, task, status, {"projection_message_index": None})

    _, run_values, task_values = finish.call_args.args
    assert run_values["status"] == status
    assert run_values["finished_at"] == (active["finished_at"] if kind == "canceled" else now)
    assert task_values["status"] == ("PAUSED_BY_SYSTEM" if kind in {"repeated-failure", "stale-receipt"} else (
        "PAUSED" if kind == "pause-race" else "ACTIVE"
    ))
    assert task_values["fire_count"] == 4
    assert task_values["consecutive_failures"] == (
        5 if kind in {"repeated-failure", "stale-receipt"} else 4 if kind == "canceled" else 0
    )
    if recovered:
        assert result is recovered
        read.assert_called_once_with(9, TENANT, ACTOR)
    else:
        assert result == run_values
        read.assert_not_called()
