# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Evaluation claim and dispatch regressions at the new Management owner."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from contracts.errors.exceptions import AppException
from contracts.evaluation import EvalRunStatus
from management.services.evaluation import dispatch as service, execution
from management.services.evaluation.dispatch import dispatch_agent_evaluation_run


def test_dispatch_claims_pending_run_and_submits_management_worker(monkeypatch):
    monkeypatch.setattr(
        service,
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
    monkeypatch.setattr(service, "claim_agent_evaluation_run", claim)
    executor = MagicMock()
    monkeypatch.setattr(execution, "execute_agent_evaluation_run", executor)
    submit = MagicMock()
    monkeypatch.setattr(service.config_thread_manager, "submit", submit)

    result = dispatch_agent_evaluation_run(7, "u1", "t1")

    assert result == {"accepted": True, "agent_evaluation_id": 7}
    claim.assert_called_once_with(agent_evaluation_id=7, tenant_id="t1", updated_by="u1")
    submitted = submit.call_args.args
    assert submitted[0] == "evaluation"
    assert submitted[1].task_name == "agent-evaluation-dispatch"
    assert submitted[1].run_id == "7"
    assert submitted[2:] == (
        executor,
        "t1",
        "u1",
        7,
        7782,
    )


def test_dispatch_is_idempotent_when_run_is_already_running(monkeypatch):
    monkeypatch.setattr(
        service,
        "get_agent_evaluation",
        MagicMock(return_value={"agent_evaluation_id": 7, "status": EvalRunStatus.RUNNING}),
    )
    submit = MagicMock()
    monkeypatch.setattr(service.config_thread_manager, "submit", submit)

    result = dispatch_agent_evaluation_run(7, "u1", "t1")

    assert result == {
        "accepted": True,
        "already_running": True,
        "agent_evaluation_id": 7,
    }
    submit.assert_not_called()


def test_dispatch_returns_not_found_for_missing_run(monkeypatch):
    monkeypatch.setattr(service, "get_agent_evaluation", lambda **_: None)

    with pytest.raises(HTTPException) as exc_info:
        dispatch_agent_evaluation_run(7, "u1", "t1")

    assert exc_info.value.status_code == 404


def test_dispatch_maps_database_exception_to_not_found(monkeypatch):
    monkeypatch.setattr(
        service,
        "get_agent_evaluation",
        MagicMock(side_effect=AppException("missing", "run missing")),
    )

    with pytest.raises(HTTPException) as exc_info:
        dispatch_agent_evaluation_run(7, "u1", "t1")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "run missing"


def test_dispatch_is_idempotent_when_pending_claim_is_lost(monkeypatch):
    monkeypatch.setattr(
        service,
        "get_agent_evaluation",
        MagicMock(
            side_effect=[
                {"agent_evaluation_id": 7, "status": EvalRunStatus.PENDING},
                {"agent_evaluation_id": 7, "status": EvalRunStatus.RUNNING},
            ]
        ),
    )
    monkeypatch.setattr(service, "claim_agent_evaluation_run", lambda **_: False)
    submit = MagicMock()
    monkeypatch.setattr(service.config_thread_manager, "submit", submit)

    result = dispatch_agent_evaluation_run(7, "u1", "t1")

    assert result == {
        "accepted": True,
        "already_running": True,
        "agent_evaluation_id": 7,
    }
    submit.assert_not_called()


def test_dispatch_rejects_pending_claim_conflict(monkeypatch):
    monkeypatch.setattr(
        service,
        "get_agent_evaluation",
        MagicMock(
            side_effect=[
                {"agent_evaluation_id": 7, "status": EvalRunStatus.PENDING},
                {"agent_evaluation_id": 7, "status": EvalRunStatus.PENDING},
            ]
        ),
    )
    monkeypatch.setattr(service, "claim_agent_evaluation_run", lambda **_: False)

    with pytest.raises(HTTPException) as exc_info:
        dispatch_agent_evaluation_run(7, "u1", "t1")

    assert exc_info.value.status_code == 409


def test_dispatch_rejects_unknown_status(monkeypatch):
    monkeypatch.setattr(
        service,
        "get_agent_evaluation",
        lambda **_: {"agent_evaluation_id": 7, "status": "CANCELLED"},
    )

    with pytest.raises(HTTPException) as exc_info:
        dispatch_agent_evaluation_run(7, "u1", "t1")

    assert exc_info.value.status_code == 409


def test_dispatch_maps_management_pool_submission_failure(monkeypatch):
    monkeypatch.setattr(
        service,
        "get_agent_evaluation",
        lambda **_: {
            "agent_evaluation_id": 7,
            "status": EvalRunStatus.PENDING,
            "judge_model_id": 7782,
        },
    )
    monkeypatch.setattr(service, "claim_agent_evaluation_run", lambda **_: True)
    monkeypatch.setattr(
        service.config_thread_manager,
        "submit",
        MagicMock(side_effect=RuntimeError("pool closed")),
    )

    release = MagicMock()
    monkeypatch.setattr(service, "release_agent_evaluation_claim", release)
    with pytest.raises(HTTPException) as exc_info:
        dispatch_agent_evaluation_run(7, "u1", "t1")

    assert exc_info.value.status_code == 500
    release.assert_called_once_with(7, "t1", "u1")
