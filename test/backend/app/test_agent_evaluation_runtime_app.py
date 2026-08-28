"""Tests for runtime-owned evaluation dispatch."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import apps.agent_evaluation_runtime_app as runtime_app
from apps.agent_evaluation_runtime_app import (
    EvaluationRunRequest,
    dispatch_evaluation_run_api,
)
from consts.evaluation_status import EvalRunStatus
from consts.exceptions import AppException


@pytest.mark.asyncio
async def test_dispatch_claims_pending_run_and_submits_runtime_worker(monkeypatch):
    monkeypatch.setattr(runtime_app, "verify_internal_runtime_jwt", lambda _: ("u1", "t1"))
    monkeypatch.setattr(
        runtime_app,
        "get_agent_evaluation",
        MagicMock(
            return_value={
                "agent_evaluation_id": 7,
                "status": EvalRunStatus.PENDING,
                "judge_model_id": 7782,
            }
        ),
    )
    claim = MagicMock(return_value=True)
    monkeypatch.setattr(runtime_app, "claim_agent_evaluation_run", claim)
    executor = MagicMock()
    monkeypatch.setattr(runtime_app, "_load_evaluation_executor", lambda: executor)
    submit = MagicMock()
    monkeypatch.setattr(runtime_app.pool, "submit", submit)

    result = await dispatch_evaluation_run_api(
        EvaluationRunRequest(agent_evaluation_id=7), "internal-token"
    )

    assert result == {"accepted": True, "agent_evaluation_id": 7}
    claim.assert_called_once_with(agent_evaluation_id=7, tenant_id="t1", updated_by="u1")
    submit.assert_called_once_with(
        executor,
        "t1",
        "u1",
        7,
        7782,
    )


@pytest.mark.asyncio
async def test_dispatch_is_idempotent_when_run_is_already_running(monkeypatch):
    monkeypatch.setattr(runtime_app, "verify_internal_runtime_jwt", lambda _: ("u1", "t1"))
    monkeypatch.setattr(
        runtime_app,
        "get_agent_evaluation",
        MagicMock(return_value={"agent_evaluation_id": 7, "status": EvalRunStatus.RUNNING}),
    )
    monkeypatch.setattr(runtime_app, "_load_evaluation_executor", lambda: MagicMock())
    submit = MagicMock()
    monkeypatch.setattr(runtime_app.pool, "submit", submit)

    result = await dispatch_evaluation_run_api(
        EvaluationRunRequest(agent_evaluation_id=7), "internal-token"
    )

    assert result == {
        "accepted": True,
        "already_running": True,
        "agent_evaluation_id": 7,
    }
    submit.assert_not_called()


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
    monkeypatch.setattr(runtime_app, "get_agent_evaluation", lambda **_: None)

    payload = EvaluationRunRequest(agent_evaluation_id=7)
    with pytest.raises(HTTPException) as exc_info:
        await dispatch_evaluation_run_api(payload, "internal-token")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_dispatch_maps_database_exception_to_not_found(monkeypatch):
    monkeypatch.setattr(runtime_app, "verify_internal_runtime_jwt", lambda _: ("u1", "t1"))
    monkeypatch.setattr(
        runtime_app,
        "get_agent_evaluation",
        MagicMock(side_effect=AppException("missing", "run missing")),
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
        "get_agent_evaluation",
        MagicMock(
            side_effect=[
                {"agent_evaluation_id": 7, "status": EvalRunStatus.PENDING},
                {"agent_evaluation_id": 7, "status": EvalRunStatus.RUNNING},
            ]
        ),
    )
    monkeypatch.setattr(runtime_app, "claim_agent_evaluation_run", lambda **_: False)
    submit = MagicMock()
    monkeypatch.setattr(runtime_app.pool, "submit", submit)

    result = await dispatch_evaluation_run_api(
        EvaluationRunRequest(agent_evaluation_id=7), "internal-token"
    )

    assert result == {
        "accepted": True,
        "already_running": True,
        "agent_evaluation_id": 7,
    }
    submit.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_rejects_pending_claim_conflict(monkeypatch):
    monkeypatch.setattr(runtime_app, "verify_internal_runtime_jwt", lambda _: ("u1", "t1"))
    monkeypatch.setattr(
        runtime_app,
        "get_agent_evaluation",
        MagicMock(
            side_effect=[
                {"agent_evaluation_id": 7, "status": EvalRunStatus.PENDING},
                {"agent_evaluation_id": 7, "status": EvalRunStatus.PENDING},
            ]
        ),
    )
    monkeypatch.setattr(runtime_app, "claim_agent_evaluation_run", lambda **_: False)
    payload = EvaluationRunRequest(agent_evaluation_id=7)

    with pytest.raises(HTTPException) as exc_info:
        await dispatch_evaluation_run_api(payload, "internal-token")

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_dispatch_rejects_unknown_status(monkeypatch):
    monkeypatch.setattr(runtime_app, "verify_internal_runtime_jwt", lambda _: ("u1", "t1"))
    monkeypatch.setattr(
        runtime_app,
        "get_agent_evaluation",
        lambda **_: {"agent_evaluation_id": 7, "status": "CANCELLED"},
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
        "get_agent_evaluation",
        lambda **_: {
            "agent_evaluation_id": 7,
            "status": EvalRunStatus.PENDING,
            "judge_model_id": 7782,
        },
    )
    monkeypatch.setattr(runtime_app, "claim_agent_evaluation_run", lambda **_: True)
    monkeypatch.setattr(runtime_app, "_load_evaluation_executor", MagicMock())
    monkeypatch.setattr(runtime_app.pool, "submit", MagicMock(side_effect=RuntimeError("pool closed")))
    payload = EvaluationRunRequest(agent_evaluation_id=7)

    with pytest.raises(HTTPException) as exc_info:
        await dispatch_evaluation_run_api(payload, "internal-token")

    assert exc_info.value.status_code == 500
