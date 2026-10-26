# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Query, Session

from management.db.conversation import repository as db
from management.services.conversation import service as conversations
from contracts.errors.exceptions import WorkbenchConfigVersionConflict
from contracts.knowledge import ConversationKnowledgeScopeRequest
from contracts.agent import WorkbenchSessionConfig


def scope(provider, ids):
    key = "knowledge_ids" if provider == "local" else "kds_ids"
    return ConversationKnowledgeScopeRequest.model_validate({
        provider: {"mode": "override", key: ids},
    }).model_dump(mode="json")


def record(value, *, canonical=True):
    config = WorkbenchSessionConfig.model_validate({
        "mode": "generic_chat", "knowledge_scope": value,
    }).model_dump(mode="json") if canonical else None
    return SimpleNamespace(knowledge_scope=deepcopy(value), workbench_config=config,
                           workbench_config_version=4 if canonical else 0, agent_id=7)


@pytest.fixture
def database(monkeypatch):
    rows, statements = [], []

    def read(query):
        compiled = query.statement.compile(dialect=postgresql.dialect())
        statements.append(compiled)
        if "knowledge_record_t" in str(compiled):
            return [SimpleNamespace(knowledge_id=213)]
        return rows

    # Construct real ORM queries; replace only database execution.
    monkeypatch.setattr(Query, "all", read)
    with Session() as session:
        yield session, rows, statements


@pytest.mark.parametrize("provider,argument", [("local", "index_names"), ("aidp", "kds_ids")])
def test_removing_last_selection_disables_both_scope_copies(database, provider, argument):
    session, rows, statements = database
    row = record(scope(provider, ["213"]))
    rows.append(row)
    original = deepcopy(row.workbench_config)
    db.remove_conversation_knowledge_bindings(session, **{argument: ["idx-a" if provider == "local" else "213"]})
    key = "knowledge_ids" if provider == "local" else "kds_ids"
    assert row.knowledge_scope[provider] == {"mode": "disabled", key: []}
    assert row.workbench_config["knowledge_scope"] == row.knowledge_scope
    assert row.workbench_config_version == 5
    assert original["knowledge_scope"][provider][key] == ["213"]
    assert row.workbench_config["mode"] == original["mode"]
    sql = str(statements[-1])
    assert "FOR UPDATE" in sql
    assert " LIKE " not in sql
    assert sql.count("@>") == 2
    assert {provider: {key: ["213"]}} in statements[-1].params.values()
    assert {"knowledge_scope": {provider: {key: ["213"]}}} in statements[-1].params.values()
    if provider == "local":
        assert len(statements) == 2
        assert "knowledge_record_t.knowledge_id" in str(statements[0])
        assert "knowledge_record_t.knowledge_name" not in str(statements[0])
        assert "delete_flag" not in str(statements[0])
    else:
        assert len(statements) == 1


def test_partial_batch_keeps_remaining_selection_and_other_provider(database):
    session, rows, _ = database
    value = scope("aidp", ["213", "214", "1213"])
    value["local"] = {"mode": "override", "knowledge_ids": ["213"]}
    row = record(value)
    rows.append(row)
    db.remove_conversation_knowledge_bindings(session, kds_ids=["213", "214"])
    assert row.knowledge_scope["aidp"] == {"mode": "override", "kds_ids": ["1213"]}
    assert row.knowledge_scope["local"] == value["local"]
    assert row.workbench_config_version == 5


@pytest.mark.parametrize("canonical,projection", [(False, True), (True, False)])
def test_nullable_scope_copies_follow_the_schema(database, canonical, projection):
    session, rows, _ = database
    row = record(scope("aidp", ["213"]), canonical=canonical)
    if not projection:
        row.knowledge_scope = None
    rows.append(row)
    db.remove_conversation_knowledge_bindings(session, kds_ids=["213"])
    if canonical:
        assert row.workbench_config["knowledge_scope"]["aidp"] == {"mode": "disabled", "kds_ids": []}
        assert row.workbench_config_version == 5
        assert row.knowledge_scope is None
    else:
        assert row.knowledge_scope["aidp"] == {"mode": "disabled", "kds_ids": []}
        assert row.workbench_config is None
        assert row.workbench_config_version == 0


def test_unchanged_canonical_config_does_not_increment_version(database):
    session, rows, _ = database
    row = record(None)
    row.knowledge_scope = scope("aidp", ["213"])
    rows.append(row)
    db.remove_conversation_knowledge_bindings(session, kds_ids=["213"])
    assert row.knowledge_scope["aidp"]["mode"] == "disabled"
    assert row.workbench_config["knowledge_scope"] is None
    assert row.workbench_config_version == 4


def test_stale_save_cannot_restore_deleted_binding(database, monkeypatch):
    session, rows, _ = database
    row = record(scope("aidp", ["213"]))
    stale = deepcopy(row.workbench_config)
    rows.append(row)
    db.remove_conversation_knowledge_bindings(session, kds_ids=["213"])
    save_session = MagicMock()
    save_session.scalars.return_value.first.return_value = row
    monkeypatch.setattr(db, "get_db_session", lambda: nullcontext(save_session))
    monkeypatch.setattr(conversations, "replace_conversation_workbench_config", db.replace_conversation_workbench_config)
    with pytest.raises(WorkbenchConfigVersionConflict):
        conversations.update_conversation_workbench_config_service(
            conversation_id=42, config=stale, expected_version=4, user_id="user",
        )
    assert row.workbench_config["knowledge_scope"]["aidp"]["kds_ids"] == []
    save_session.flush.assert_not_called()


def test_empty_batch_does_not_query(database):
    session, _, statements = database
    assert db.remove_conversation_knowledge_bindings(session) is None
    assert statements == []


def test_database_error_propagates_to_best_effort_deletion_service(monkeypatch):
    session = MagicMock()
    session.query.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError, match="database unavailable"):
        db.remove_conversation_knowledge_bindings(session, kds_ids=["213"])
