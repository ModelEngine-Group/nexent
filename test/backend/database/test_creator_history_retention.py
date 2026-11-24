# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Agent and Skill creator retention scopes and transaction ownership."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from management.db.conversation import repository as db


@pytest.fixture
def session(monkeypatch):
    value = MagicMock()

    @contextmanager
    def sessions():
        yield value

    monkeypatch.setattr(db, "get_db_session", sessions)
    return value


@pytest.mark.parametrize("kind", ["agent", "skill"])
@pytest.mark.parametrize("excess", [[], [4], [4, 3, 2, 1]])
def test_retention_orders_and_scopes_excess_in_shared_transaction(session, mocker, excess, kind):
    session.scalars.return_value.all.return_value = excess
    delete = mocker.patch.object(db, "delete_conversations_batch", return_value=excess)
    target = {"type": kind, "id": 201}
    db.retain_creator_histories("owner", 77, target, session=session)
    lock = session.execute.call_args_list[0]
    assert "pg_advisory_xact_lock" in str(lock.args[0])
    assert lock.args[1]["lock_key"] == f"creator-history:owner:77:{kind}:201"
    statement = session.scalars.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert compiled.params["created_by_1"] == "owner"
    assert compiled.params["agent_id_1"] == 77
    assert compiled.params["target_1"] == target
    assert compiled.params["delete_flag_1"] == "N"
    assert compiled.params["param_1"] == 3
    assert "coalesce" in str(statement) and "conversation_id DESC" in str(statement)
    if excess:
        delete.assert_called_once_with(excess, "owner", session=session)
    else:
        delete.assert_not_called()
    session.commit.assert_not_called()


@pytest.mark.parametrize("target,user", [({"type": "file", "id": 201}, "owner"), (None, "owner"), ({"type": "agent", "id": 201}, None)])
def test_retention_never_touches_other_conversation_kinds(session, target, user):
    db.retain_creator_histories(user, 77, target, session=session)
    session.execute.assert_not_called()
    session.scalars.assert_not_called()


def test_retention_propagates_delete_failure(session, mocker):
    session.scalars.return_value.all.return_value = [4]
    mocker.patch.object(db, "delete_conversations_batch", side_effect=RuntimeError("write failed"))
    with pytest.raises(RuntimeError, match="write failed"):
        db.retain_creator_histories("owner", 77, {"type": "agent", "id": 201})


def test_cascade_reuses_callers_transaction_and_audits_all_children(session, mocker):
    summaries = mocker.patch("management.db.trajectory.repository.delete_summaries")
    session.execute.return_value.all.return_value = [(4,)]
    assert db.delete_conversations_batch([4, 999], "owner", session=session) == [4]
    summaries.assert_called_once_with(session, [4], "owner")
    writes = [call.args[0] for call in session.execute.call_args_list if call.args[0].is_update]
    assert len(writes) == 5
    for statement in writes:
        values = statement.compile(dialect=postgresql.dialect()).params
        assert values["delete_flag"] == "Y"
        assert values["updated_by"] == "owner"
        assert values["conversation_id_1"] == [4]
    session.commit.assert_not_called()
    session.close.assert_not_called()


@pytest.mark.parametrize("kind", ["agent", "skill"])
def test_creation_enforces_retention_before_returning_new_conversation(session, mocker, kind):
    mocker.patch.object(db, "_enforce_user_conversation_limit")
    mocker.patch("management.db.trajectory.repository.seed_conversation")
    retain = mocker.patch.object(db, "retain_creator_histories")
    target = {"type": kind, "id": 201}
    session.execute.return_value.fetchone.return_value = SimpleNamespace(
        conversation_id=9, conversation_title="Create", agent_id=77, target=target,
        chat_mode=None, knowledge_scope=None, runtime_metadata=None, runtime_metadata_version=0,
        workbench_config=None, workbench_config_version=0, create_time=1000, update_time=1000,
    )
    assert db.create_conversation("Create", "owner", agent_id=77, target=target)["conversation_id"] == 9
    retain.assert_called_once_with("owner", 77, target, session=session)
    assert "pg_advisory_xact_lock" in str(session.execute.call_args_list[0].args[0])


@pytest.mark.parametrize("kind", ["agent", "skill"])
@pytest.mark.parametrize("affected", [0, 1])
def test_binding_enforces_retention_only_after_successful_compare_and_set(session, mocker, affected, kind):
    retain = mocker.patch.object(db, "retain_creator_histories")
    session.execute.return_value.rowcount = affected
    target = {"type": kind, "id": 201}
    assert db.bind_creation_conversation_target(9, 77, None, target, "owner") is bool(affected)
    if affected:
        retain.assert_called_once_with("owner", 77, target, session=session)
    else:
        retain.assert_not_called()
