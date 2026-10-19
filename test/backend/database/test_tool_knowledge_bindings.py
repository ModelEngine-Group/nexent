# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace
from unittest.mock import MagicMock

import database.tool_db as tool_db
import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session


@pytest.mark.parametrize("param_name,tool_name", [
    ("index_names", "knowledge_base_search"), ("kds_list", "aidp_search"),
])
def test_reference_query_filters_tool_and_ids_in_postgresql(param_name, tool_name):
    with Session() as session:
        query = tool_db._query_knowledge_tool_instances(session, param_name, {"one", "two"})
        compiled = query.statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "JOIN nexent.ag_tool_info_t" in sql
    assert "ag_tool_info_t.tool_id = nexent.ag_tool_instance_t.tool_id" in sql
    assert "ag_tool_info_t.name =" in sql
    assert "ag_tool_info_t.delete_flag !=" in sql
    assert "ag_tool_instance_t.delete_flag !=" in sql
    assert "CAST(" in sql and "AS JSONB) @>" in sql
    assert " OR " in sql
    assert tool_name in compiled.params.values()
    assert param_name in compiled.params.values()
    assert ["one"] in compiled.params.values()
    assert ["two"] in compiled.params.values()


def test_preview_selects_only_agent_and_version(monkeypatch):
    query = MagicMock()
    query.with_entities.return_value.distinct.return_value.all.return_value = [
        SimpleNamespace(agent_id=7, version_no=0), SimpleNamespace(agent_id=7, version_no=2),
    ]
    monkeypatch.setattr(tool_db, "_query_knowledge_tool_instances", lambda *args: query)
    assert tool_db.query_tool_knowledge_references(MagicMock(), "index_names", {"idx"}) == [
        {"agent_id": 7, "version_no": 0}, {"agent_id": 7, "version_no": 2},
    ]
    query.with_entities.assert_called_once_with(
        tool_db.ToolInstance.agent_id, tool_db.ToolInstance.version_no,
    )
    query.with_entities.return_value.distinct.assert_called_once_with()


@pytest.mark.parametrize("param_name,argument", [("index_names", "index_names"), ("kds_list", "kds_ids")])
def test_cleanup_removes_only_deleted_ids_and_preserves_other_params(monkeypatch, param_name, argument):
    instance = SimpleNamespace(params={param_name: ["one", "two", "keep"], "top_k": 7})
    original = instance.params
    query = MagicMock()
    query.all.return_value = [instance]
    selector = MagicMock(return_value=query)
    monkeypatch.setattr(tool_db, "_query_knowledge_tool_instances", selector)
    session = MagicMock()
    assert tool_db.remove_tool_knowledge_references(session, **{argument: ["one", "two", "one"]}) is None
    selector.assert_called_once_with(session, param_name, {"one", "two"})
    assert instance.params == {param_name: ["keep"], "top_k": 7}
    assert original == {param_name: ["one", "two", "keep"], "top_k": 7}
    assert instance.params is not original
    session.commit.assert_not_called()


def test_empty_cleanup_does_not_query(monkeypatch):
    selector = MagicMock()
    monkeypatch.setattr(tool_db, "_query_knowledge_tool_instances", selector)
    tool_db.remove_tool_knowledge_references(MagicMock())
    selector.assert_not_called()


def test_cleanup_database_error_reaches_deletion_service(monkeypatch):
    query = MagicMock()
    query.all.side_effect = RuntimeError("database unavailable")
    monkeypatch.setattr(tool_db, "_query_knowledge_tool_instances", lambda *args: query)
    with pytest.raises(RuntimeError, match="database unavailable"):
        tool_db.remove_tool_knowledge_references(MagicMock(), kds_ids=["one"])
