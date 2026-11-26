# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contextlib import nullcontext
from unittest.mock import Mock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError

from contracts.errors.exceptions import AgentRunConcurrencyExceededError
from infrastructure.rdb import agent_execution as execution


@pytest.fixture
def owned_session(monkeypatch):
    session = Mock()
    monkeypatch.setattr(execution, "get_db_session", lambda: nullcontext(session))
    owner_check = Mock(return_value=True)
    monkeypatch.setattr(execution, "_owned_conversation", owner_check)
    return session, owner_check


def test_shared_admission_locks_scope_and_authorizes_conversation_before_counting(owned_session):
    session, owner_check = owned_session
    identity = execution.RunIdentity("t1", "u1", 5, "a" * 32)
    observations = []

    def authorize(*args, **kwargs):
        assert session.execute.call_count == 1
        assert "pg_advisory_xact_lock" in str(session.execute.call_args.args[0])
        assert kwargs == {"lock": True}
        assert args == (session, 5, "u1", "t1")
        observations.append("owned")
        return True

    def query(statement):
        assert observations == ["owned"]
        return next(results)

    owner_check.side_effect = authorize
    results = iter([None, 1, identity.run_id])
    session.scalar.side_effect = query

    execution.begin_execution(identity, agent_scope="agent:4", agent_limit=2)

    active, quota, inserted = (item.args[0] for item in session.scalar.call_args_list)
    assert active.compile().params["conversation_id_1"] == 5
    assert quota.compile().params["agent_scope_1"] == "agent:4"
    params = inserted.compile(dialect=postgresql.dialect()).params
    assert params["run_id"] == identity.run_id
    assert params["status"] == "starting"
    assert params["owner_id"] == execution.OWNER_ID


@pytest.mark.parametrize(
    ("results", "error"),
    [
        (["other-run"], execution.ActiveExecutionError),
        ([None, 2], AgentRunConcurrencyExceededError),
        ([None, 1, None], execution.ActiveExecutionError),
    ],
)
def test_shared_admission_rejects_existing_execution_full_quota_or_reused_run_id(owned_session, results, error):
    session, _ = owned_session
    session.scalar.side_effect = results
    identity = execution.RunIdentity("t1", "u1", 5, "a" * 32)

    with pytest.raises(error):
        execution.begin_execution(identity, agent_scope="agent:4", agent_limit=2)

    assert session.scalar.call_count == len(results)


def test_unavailable_database_fails_admission_before_contacting_execution(owned_session):
    session, owner_check = owned_session
    session.execute.side_effect = OperationalError(None, None, RuntimeError("offline"))
    identity = execution.RunIdentity("t1", "u1", 5, "a" * 32)

    with pytest.raises(OperationalError):
        execution.begin_execution(identity, agent_scope="agent:4", agent_limit=2)

    owner_check.assert_not_called()
    session.scalar.assert_not_called()


@pytest.mark.parametrize("active_only", [False, True])
def test_creator_read_is_scoped_to_owner_conversation_and_exact_creator(owned_session, active_only):
    session, owner_check = owned_session
    session.execute.return_value.one_or_none.return_value = Mock(
        run_id="a" * 32, status="running", agent_scope="nl2skill_main",
    )

    assert execution.find_owned_agent_execution(
        "t1", "u1", 5, agent_scope="nl2skill_main", active_only=active_only,
    ) == ("a" * 32, "running", "nl2skill_main")

    owner_check.assert_called_once_with(session, 5, "u1", "t1")
    params = session.execute.call_args.args[0].compile().params
    assert params["agent_scope_1"] == "nl2skill_main"
    assert params["conversation_id_1"] == 5
    assert params["tenant_id_1"] == "t1"
    assert params["created_by_1"] == "u1"
    assert ("status_1" in params) is active_only


def test_ordinary_runtime_lookup_omits_management_creator_rows(owned_session):
    session, _ = owned_session
    session.scalar.return_value = None

    assert execution.read_execution("a" * 32, "u1", "t1", 5, request_stop=True) is None

    query = session.scalar.call_args.args[0]
    assert query.compile().params["agent_scope_1"] == ["nl2agent_main", "nl2skill_main"] or (
        query.compile().params["agent_scope_1"] == ("nl2agent_main", "nl2skill_main")
    )
    assert "agent_scope IS NULL" in str(query)


def test_creator_terminal_write_releases_lease_without_enqueuing_agentos_journal_repair(owned_session):
    session, _ = owned_session
    session.execute.return_value.rowcount = 1
    identity = execution.RunIdentity("t1", "u1", 5, "a" * 32)
    execution.track_execution(identity)

    assert execution.finish_execution(identity, "completed", repair_journal=False)

    params = session.execute.call_args.args[0].compile().params
    assert params["status"] == "completed"
    assert params["lease_until"] is None
    assert params["journal_repair_pending"] is False
    assert params["owner_id_1"] == execution.OWNER_ID
    assert identity.run_id not in execution._live_run_ids
