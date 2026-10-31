# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Creator history writes and queries retain owner, executor and target boundaries."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from management.db.conversation import repository as db
from management.services.conversation import service


@pytest.fixture
def session(monkeypatch):
    value = MagicMock()

    @contextmanager
    def sessions():
        yield value

    monkeypatch.setattr(db, "get_db_session", sessions)
    return value


@pytest.mark.parametrize("previous", [None, {"type": "agent", "id": 200}])
@pytest.mark.parametrize("affected", [0, 1])
def test_bind_target_is_owner_scoped_compare_and_set(session, previous, affected):
    target = {"type": "agent", "id": 201}
    session.execute.return_value.rowcount = affected
    assert db.bind_creation_conversation_target(9, 77, previous, target, "owner") is (affected == 1)
    statement = session.execute.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    predicates = str(statement.whereclause.compile(dialect=postgresql.dialect()))
    assert compiled.params["target"] == target and compiled.params["updated_by"] == "owner"
    assert compiled.params["conversation_id_1"] == 9
    assert compiled.params["agent_id_1"] == 77
    assert compiled.params["created_by_1"] == "owner"
    assert compiled.params["delete_flag_1"] == "N"
    if previous is None:
        assert "target IS NULL" in predicates
    else:
        assert compiled.params["target_1"] == previous
    assert "agent_id=" not in str(compiled).split(" WHERE ")[0]


@pytest.mark.parametrize("executor,target", [(77, None), (None, {"type": "skill", "id": 201})])
def test_history_filters_require_executor_and_target_together(session, executor, target):
    with pytest.raises(ValueError, match="must be supplied together"):
        db.get_conversation_list_page("owner", 2000, 1000, creator_agent_id=executor, creator_target=target)
    session.execute.assert_not_called()


def test_creator_filter_scopes_both_page_and_empty_page_counts(session):
    counts = MagicMock()
    counts.one.return_value = SimpleNamespace(total=2, today=1, last_7_days=1, older=0)
    session.execute.side_effect = [[], counts]
    target = {"type": "skill", "id": 201}
    result = db.get_conversation_list_page(
        "owner", 2000, 1000, limit=2, offset=2, creator_agent_id=77, creator_target=target,
    )
    assert result == {"items": [], "next_cursor": None, "metadata": {"total": 2, "today": 1, "last_7_days": 1, "older": 0}}
    assert session.execute.call_count == 2
    for call in session.execute.call_args_list:
        values = call.args[0].compile(dialect=postgresql.dialect()).params
        assert values["agent_id_1"] == 77 and values["target_1"] == target
        assert values["created_by_1"] == "owner" and values["delete_flag_1"] == "N"


def test_creation_copies_target_before_insert_and_returns_it(session):
    target = {"type": "skill", "id": 201}
    session.execute.return_value.fetchone.return_value = SimpleNamespace(
        conversation_id=9, conversation_title="Create", agent_id=77, target=target,
        chat_mode=None, knowledge_scope=None, runtime_metadata=None, runtime_metadata_version=0,
        workbench_config=None, workbench_config_version=0, create_time=1000, update_time=1000,
    )
    result = db.create_conversation("Create", agent_id=77, target=target)
    values = session.execute.call_args.args[0].compile(dialect=postgresql.dialect()).params
    assert values["target"] == target and values["target"] is not target
    target["id"] = 999
    assert values["target"]["id"] == 201
    assert result["conversation_id"] == 9 and result["agent_id"] == 77


def test_service_forwards_explicit_target_to_creation_repository(mocker):
    target = {"type": "skill", "id": 201}
    create = mocker.patch.object(service, "create_conversation", return_value={"conversation_id": 9})
    assert service.create_new_conversation("Create", "owner", agent_id=77, target=target) == {"conversation_id": 9}
    create.assert_called_once_with("Create", "owner", agent_id=77, chat_mode=None, target=target)
