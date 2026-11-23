# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Tests for runtime-owned evaluation dispatch."""

from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from runtime.api.evaluation import execution as runtime_app
from contracts.evaluation import EvaluationRunRequest, RuntimeEvaluationTrialRunRequest as TrialRunRequest
from runtime.api.evaluation.execution import dispatch_evaluation_run_api, trial_run_evaluation_api
from contracts.evaluation import EvalRunStatus
from contracts.errors.exceptions import AppException
from management.services.evaluation import dispatch as dispatch_service
from management.services.execution_coordination import ExecutionAlreadyActiveError, RuntimeCoordinationUnavailableError
from nexent.core.concurrency import ThreadCapacityExceeded, ThreadManagerDraining, ThreadManagerNotRunning, ThreadQueueTimedOut


@pytest.mark.asyncio
async def test_trial_run_uses_internal_identity_and_runtime_executor(monkeypatch):
    monkeypatch.setattr(runtime_app, "verify_internal_runtime_jwt", lambda _: ("u1", "t1"))
    executor = AsyncMock(return_value={"answer": "ok", "scores": {"judge": 1.0}})
    monkeypatch.setattr(runtime_app, "_load_trial_executor", lambda: executor)

    result = await trial_run_evaluation_api(
        TrialRunRequest(
            agent_id=7,
            agent_version_no=3,
            query="hello",
            judge_model_id=99,
            evaluator_ids=[5],
        ),
        "internal-token",
    )

    assert result == {"answer": "ok", "scores": {"judge": 1.0}}
    executor.assert_awaited_once_with(
        tenant_id="t1",
        user_id="u1",
        agent_id=7,
        agent_version_no=3,
        query="hello",
        judge_model_id=99,
        evaluator_ids=[5],
        language="zh",
    )


@pytest.mark.asyncio
async def test_trial_run_rejects_missing_internal_token_without_executing(monkeypatch):
    monkeypatch.setattr(
        runtime_app,
        "verify_internal_runtime_jwt",
        MagicMock(side_effect=ValueError("invalid token")),
    )
    load_executor = MagicMock()
    monkeypatch.setattr(runtime_app, "_load_trial_executor", load_executor)

    with pytest.raises(HTTPException) as exc_info:
        await trial_run_evaluation_api(
            TrialRunRequest(agent_id=7, query="hello", judge_model_id=99),
            None,
        )

    assert exc_info.value.status_code == 401
    load_executor.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_claims_pending_run_and_submits_runtime_worker(monkeypatch):
    monkeypatch.setattr(runtime_app, "verify_internal_runtime_jwt", lambda _: ("u1", "t1"))
    monkeypatch.setattr(
        runtime_app,
        "read_evaluation_for_dispatch",
        AsyncMock(
            return_value={
                "agent_evaluation_id": 7,
                "status": EvalRunStatus.PENDING,
                "judge_model_id": 7782,
            }
        ),
    )
    executor = MagicMock()
    monkeypatch.setattr(runtime_app, "_load_evaluation_executor", lambda: executor)
    start = AsyncMock()
    monkeypatch.setattr(runtime_app, "start_pending_evaluation", start)

    result = await dispatch_evaluation_run_api(
        EvaluationRunRequest(agent_evaluation_id=7), "internal-token"
    )

    assert result == {"accepted": True, "agent_evaluation_id": 7}
    start.assert_awaited_once_with(7, "t1", "u1", 7782, executor)


@pytest.mark.asyncio
async def test_dispatch_is_idempotent_when_run_is_already_running(monkeypatch):
    monkeypatch.setattr(runtime_app, "verify_internal_runtime_jwt", lambda _: ("u1", "t1"))
    monkeypatch.setattr(
        runtime_app,
        "read_evaluation_for_dispatch",
        AsyncMock(return_value={"agent_evaluation_id": 7, "status": EvalRunStatus.RUNNING}),
    )
    monkeypatch.setattr(runtime_app, "_load_evaluation_executor", lambda: MagicMock())
    start = AsyncMock()
    monkeypatch.setattr(runtime_app, "start_pending_evaluation", start)

    result = await dispatch_evaluation_run_api(
        EvaluationRunRequest(agent_evaluation_id=7), "internal-token"
    )

    assert result == {
        "accepted": True,
        "already_running": True,
        "agent_evaluation_id": 7,
    }
    start.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_rejects_missing_internal_token(monkeypatch):
    monkeypatch.setattr(
        runtime_app,
        "verify_internal_runtime_jwt",
        MagicMock(side_effect=ValueError("invalid token")),
    )

    payload = EvaluationRunRequest(agent_evaluation_id=7)
    with pytest.raises(HTTPException) as exc_info:
        await dispatch_evaluation_run_api(payload, None)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_dispatch_returns_not_found_for_missing_run(monkeypatch):
    monkeypatch.setattr(runtime_app, "verify_internal_runtime_jwt", lambda _: ("u1", "t1"))
    monkeypatch.setattr(runtime_app, "read_evaluation_for_dispatch", AsyncMock(return_value=None))

    payload = EvaluationRunRequest(agent_evaluation_id=7)
    with pytest.raises(HTTPException) as exc_info:
        await dispatch_evaluation_run_api(payload, "internal-token")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_dispatch_maps_database_exception_to_not_found(monkeypatch):
    monkeypatch.setattr(runtime_app, "verify_internal_runtime_jwt", lambda _: ("u1", "t1"))
    monkeypatch.setattr(
        runtime_app,
        "read_evaluation_for_dispatch",
        AsyncMock(side_effect=AppException("missing", "run missing")),
    )
    payload = EvaluationRunRequest(agent_evaluation_id=7)

    with pytest.raises(HTTPException) as exc_info:
        await dispatch_evaluation_run_api(payload, "internal-token")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "run missing"


@pytest.mark.asyncio
async def test_dispatch_is_idempotent_when_pending_claim_is_lost(monkeypatch):
    monkeypatch.setattr(runtime_app, "verify_internal_runtime_jwt", lambda _: ("u1", "t1"))
    monkeypatch.setattr(
        runtime_app,
        "read_evaluation_for_dispatch",
        AsyncMock(
            side_effect=[
                {"agent_evaluation_id": 7, "status": EvalRunStatus.PENDING},
                {"agent_evaluation_id": 7, "status": EvalRunStatus.RUNNING},
            ]
        ),
    )
    start = AsyncMock(side_effect=ExecutionAlreadyActiveError("another Pod owns the claim"))
    monkeypatch.setattr(runtime_app, "start_pending_evaluation", start)
    monkeypatch.setattr(runtime_app, "_load_evaluation_executor", MagicMock())

    result = await dispatch_evaluation_run_api(
        EvaluationRunRequest(agent_evaluation_id=7), "internal-token"
    )

    assert result == {
        "accepted": True,
        "already_running": True,
        "agent_evaluation_id": 7,
    }
    start.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_rejects_pending_claim_conflict(monkeypatch):
    monkeypatch.setattr(runtime_app, "verify_internal_runtime_jwt", lambda _: ("u1", "t1"))
    monkeypatch.setattr(
        runtime_app,
        "read_evaluation_for_dispatch",
        AsyncMock(
            side_effect=[
                {"agent_evaluation_id": 7, "status": EvalRunStatus.PENDING},
                {"agent_evaluation_id": 7, "status": EvalRunStatus.PENDING},
            ]
        ),
    )
    monkeypatch.setattr(runtime_app, "start_pending_evaluation", AsyncMock(side_effect=ExecutionAlreadyActiveError()))
    monkeypatch.setattr(runtime_app, "_load_evaluation_executor", MagicMock())
    payload = EvaluationRunRequest(agent_evaluation_id=7)

    with pytest.raises(HTTPException) as exc_info:
        await dispatch_evaluation_run_api(payload, "internal-token")

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("latest_status", [EvalRunStatus.RUNNING, EvalRunStatus.PENDING])
@pytest.mark.parametrize("maintenance", [False, True])
async def test_distributed_dispatch_maps_held_reservation(monkeypatch, latest_status, maintenance):
    from runtime import identity, sandbox_evaluation, sandbox_runtime
    from runtime.sandbox_coordination import SandboxRunBusy

    monkeypatch.setattr(runtime_app, "verify_internal_runtime_jwt", lambda _: ("u1", "t1"))
    lookup = AsyncMock(side_effect=[{"status": EvalRunStatus.PENDING}, {"status": latest_status}])
    monkeypatch.setattr(runtime_app, "read_evaluation_for_dispatch", lookup)
    monkeypatch.setattr(runtime_app, "uses_durable_agent_admission", lambda: maintenance)
    monkeypatch.setattr(runtime_app, "_load_evaluation_executor", MagicMock())
    monkeypatch.setattr(identity, "uses_distributed_runtime", lambda: True)
    monkeypatch.setattr(sandbox_runtime, "require_business_admission", lambda: None)
    monkeypatch.setattr(sandbox_runtime, "get_coordinator", MagicMock())
    dispatch = AsyncMock(side_effect=SandboxRunBusy("already reserved"))
    monkeypatch.setattr(sandbox_evaluation, "dispatch_owned_evaluation", dispatch)
    durable_dispatch = AsyncMock(side_effect=ExecutionAlreadyActiveError())
    monkeypatch.setattr(runtime_app, "start_pending_evaluation", durable_dispatch)

    payload = EvaluationRunRequest(agent_evaluation_id=7)
    if latest_status == EvalRunStatus.RUNNING:
        assert await dispatch_evaluation_run_api(payload, "internal-token") == {
            "accepted": True, "already_running": True, "agent_evaluation_id": 7,
        }
    else:
        with pytest.raises(HTTPException) as exc_info:
            await dispatch_evaluation_run_api(payload, "internal-token")
        assert exc_info.value.status_code == HTTPStatus.CONFLICT
    if maintenance:
        durable_dispatch.assert_awaited_once()
        dispatch.assert_not_called()
    else:
        dispatch.assert_awaited_once()
        durable_dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_rejects_unknown_status(monkeypatch):
    monkeypatch.setattr(runtime_app, "verify_internal_runtime_jwt", lambda _: ("u1", "t1"))
    monkeypatch.setattr(
        runtime_app,
        "read_evaluation_for_dispatch",
        AsyncMock(return_value={"agent_evaluation_id": 7, "status": "CANCELLED"}),
    )
    payload = EvaluationRunRequest(agent_evaluation_id=7)

    with pytest.raises(HTTPException) as exc_info:
        await dispatch_evaluation_run_api(payload, "internal-token")

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_dispatch_maps_runtime_pool_submission_failure(monkeypatch):
    monkeypatch.setattr(runtime_app, "verify_internal_runtime_jwt", lambda _: ("u1", "t1"))
    monkeypatch.setattr(
        runtime_app,
        "read_evaluation_for_dispatch",
        AsyncMock(return_value={
            "agent_evaluation_id": 7,
            "status": EvalRunStatus.PENDING,
            "judge_model_id": 7782,
        }),
    )
    claim = MagicMock(return_value=True)
    monkeypatch.setattr(dispatch_service, "claim_agent_evaluation_run", claim)
    monkeypatch.setattr(runtime_app, "_load_evaluation_executor", MagicMock())
    monkeypatch.setattr(
        dispatch_service.runtime_thread_manager,
        "submit",
        MagicMock(side_effect=RuntimeError("pool closed")),
    )
    payload = EvaluationRunRequest(agent_evaluation_id=7)

    with pytest.raises(HTTPException) as exc_info:
        await dispatch_evaluation_run_api(payload, "internal-token")

    assert exc_info.value.status_code == 500
    claim.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(("failure", "status", "code"), [
    (RuntimeCoordinationUnavailableError(), 503, "RUNTIME_COORDINATION_UNAVAILABLE"),
    (ThreadManagerDraining(), 503, "RUNTIME_COORDINATION_UNAVAILABLE"),
    (ThreadManagerNotRunning(), 503, "RUNTIME_COORDINATION_UNAVAILABLE"),
    (ThreadCapacityExceeded("evaluation", 1, 0), 429, "RUNTIME_CAPACITY_FULL"),
    (ThreadQueueTimedOut("evaluation", 1), 429, "RUNTIME_QUEUE_TIMEOUT"),
])
async def test_dispatch_maps_admission_rejections_to_retryable_responses(monkeypatch, failure, status, code):
    monkeypatch.setattr(runtime_app, "verify_internal_runtime_jwt", lambda _: ("u1", "t1"))
    monkeypatch.setattr(runtime_app, "read_evaluation_for_dispatch", AsyncMock(return_value={"status": "PENDING"}))
    monkeypatch.setattr(runtime_app, "_load_evaluation_executor", MagicMock())
    monkeypatch.setattr(runtime_app, "start_pending_evaluation", AsyncMock(side_effect=failure))

    response = await dispatch_evaluation_run_api(EvaluationRunRequest(agent_evaluation_id=7), "internal-token")

    assert response.status_code == status
    assert response.headers["retry-after"] == "1"
    payload = response.body.decode()
    assert code in payload and '"retryable":true' in payload
