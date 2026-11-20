# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contextlib import nullcontext
from unittest.mock import Mock, call

import pytest
from sqlalchemy.exc import OperationalError

from management.services import execution_coordination as coordination


@pytest.fixture
def admission(monkeypatch):
    repository = Mock()
    repository.find_active_execution.return_value = None
    repository.count_active_agent_executions.return_value = 0
    repository.insert_preparing_execution.return_value = 17
    session = object()
    monkeypatch.setattr(coordination, "repository", repository)
    monkeypatch.setattr(coordination, "get_db_session", lambda: nullcontext(session))
    request = {
        "tenant_id": "tenant-a",
        "user_id": "user-a",
        "execution_kind": "agent",
        "execution_key": "conversation:5",
        "agent_scope": "agent:4",
        "agent_limit": 2,
        "owner_instance_id": "runtime-a:owner",
        "maintenance_epoch": "9d323186-23f6-4ab6-b0ab-8990661e6320",
    }
    return request, session, repository


def test_reservation_locks_quota_then_execution_before_reading(admission):
    request, session, repository = admission

    assert coordination.reserve_runtime_execution(**request) == 17

    assert repository.mock_calls == [
        call.lock_admission_scope(session, "agent", "tenant-a", "agent:4"),
        call.lock_admission_scope(session, "execution", "tenant-a", "conversation:5"),
        call.find_active_execution(session, "tenant-a", "conversation:5"),
        call.count_active_agent_executions(session, "tenant-a", "agent:4"),
        call.insert_preparing_execution(session, **{key: value for key, value in request.items() if key != "agent_limit"}),
    ]


def test_existing_execution_wins_over_full_quota(admission):
    request, _, repository = admission
    repository.find_active_execution.return_value = object()
    repository.count_active_agent_executions.return_value = request["agent_limit"]

    with pytest.raises(coordination.ExecutionAlreadyActiveError):
        coordination.reserve_runtime_execution(**request)

    repository.count_active_agent_executions.assert_not_called()
    repository.insert_preparing_execution.assert_not_called()


def test_agent_quota_is_checked_at_capacity_boundary(admission):
    request, _, repository = admission
    repository.count_active_agent_executions.return_value = request["agent_limit"]

    with pytest.raises(coordination.ExecutionQuotaExceededError):
        coordination.reserve_runtime_execution(**request)

    repository.insert_preparing_execution.assert_not_called()


def test_evaluation_has_no_agent_quota_lock_or_count(admission):
    request, session, repository = admission
    request.update(execution_kind="evaluation", execution_key="evaluation:8", agent_scope=None, agent_limit=None)

    assert coordination.reserve_runtime_execution(**request) == 17

    repository.lock_admission_scope.assert_called_once_with(session, "execution", "tenant-a", "evaluation:8")
    repository.count_active_agent_executions.assert_not_called()


def test_unavailable_database_does_not_fall_back_to_local_admission(admission):
    request, _, repository = admission
    repository.lock_admission_scope.side_effect = OperationalError(None, None, RuntimeError("offline"))

    with pytest.raises(coordination.RuntimeCoordinationUnavailableError):
        coordination.reserve_runtime_execution(**request)

    repository.insert_preparing_execution.assert_not_called()


def test_execution_cannot_complete_before_finalizing(admission):
    _, session, repository = admission
    repository.transition_owned_execution.return_value = False

    assert not coordination.transition_runtime_execution(17, "runtime-a:owner", "COMPLETED")

    repository.transition_owned_execution.assert_called_once_with(
        session, 17, "runtime-a:owner", ("FINALIZING",), "COMPLETED", None,
    )
