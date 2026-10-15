# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from unittest.mock import MagicMock

import pytest

import database.agent_db as agent_db
from consts.const import ASSET_OWNER_TENANT_ID


class _SequencedSession:
    def __init__(self, *results):
        self._results = list(results)
        self.commits = 0

    def query(self, *args, **kwargs):
        assert self._results, "unexpected query"
        rows = self._results.pop(0)
        query = MagicMock()
        query.filter.return_value = query
        query.all.return_value = rows if isinstance(rows, list) else [rows]
        return query

    def commit(self):
        self.commits += 1


@pytest.fixture(autouse=True)
def as_dict(monkeypatch):
    monkeypatch.setattr(agent_db, "as_dict", vars)


def test_binding_rows_dedupe_and_drop_missing_agent(monkeypatch):
    monkeypatch.setattr(
        agent_db,
        "query_tool_knowledge_bindings",
        lambda session, param_name, resource_ids: [
            {"agent_id": 7, "version_no": 0},
            {"agent_id": 7, "version_no": 0},
            {"agent_id": None, "version_no": 0},
        ],
    )
    monkeypatch.setattr(
        agent_db,
        "query_skill_knowledge_bindings",
        lambda session, param_name, resource_ids: [
            {"agent_id": 7, "version_no": 0},
            {"agent_id": 7, "version_no": 1},
        ],
    )
    rows = agent_db._query_knowledge_binding_rows(object(), [], ["kds-1"])
    keys = {
        (row["agent_id"], row["version_no"]) for row in rows
    }
    assert keys == {(7, 0), (7, 1)}


def test_live_agent_bindings_filters_deleted_versions(monkeypatch):
    monkeypatch.setattr(
        agent_db,
        "_query_knowledge_binding_rows",
        lambda session, *args: [
            {"agent_id": 7, "version_no": 0},
            {"agent_id": 7, "version_no": 1},
            {"agent_id": 8, "version_no": 0},
            {"agent_id": 9, "version_no": 1},
        ],
    )
    session = _SequencedSession([(7, 0), (7, 1), (8, 0)])
    # AgentVersion query: version 1 of agent 9 was deleted, agent 7's stayed.
    session._results = [[(7, 0), (7, 1), (8, 0)], [(7, 1)]]
    rows = agent_db.query_live_knowledge_bindings(session, kds_ids=["kds-1"])
    keys = {(row["agent_id"], row["version_no"]) for row in rows}
    assert keys == {(7, 0), (7, 1), (8, 0)}

    empty = _SequencedSession([])
    monkeypatch.setattr(
        agent_db, "_query_knowledge_binding_rows", lambda session, *args: []
    )
    assert agent_db.query_live_knowledge_bindings(empty, kds_ids=["kds-1"]) == []


def test_live_rows_draft_only_skips_version_query(monkeypatch):
    monkeypatch.setattr(
        agent_db,
        "_query_knowledge_binding_rows",
        lambda session, *args: [
            {"agent_id": 7, "version_no": 0},
        ],
    )
    session = _SequencedSession([(7, 0)])
    rows = agent_db.query_live_knowledge_bindings(session, kds_ids=["kds-1"])
    assert {(row["agent_id"], row["version_no"]) for row in rows} == {(7, 0)}
    assert len(session._results) == 0  # the AgentVersion query never ran


def test_live_rows_drop_versions_missing_from_the_version_table(monkeypatch):
    monkeypatch.setattr(
        agent_db,
        "_query_knowledge_binding_rows",
        lambda session, *args: [
            {"agent_id": 7, "version_no": 0},
            {"agent_id": 7, "version_no": 1},
        ],
    )
    session = _SequencedSession([(7, 0), (7, 1)], [])
    rows = agent_db.query_live_knowledge_bindings(session, kds_ids=["kds-1"])
    assert {(row["agent_id"], row["version_no"]) for row in rows} == {(7, 0)}


def test_binding_agent_metadata_filters_tenant_and_deduplicates_ids():
    session = MagicMock()
    query = session.query.return_value
    query.filter.return_value.all.return_value = []
    assert agent_db.query_binding_agent_metadata(session, [7, 7, 8], tenant_id="t1") == {}
    predicates = query.filter.call_args.args
    tenant = next(item for item in predicates if str(item.left).endswith(".tenant_id"))
    assert set(tenant.right.value) == {"t1", ASSET_OWNER_TENANT_ID}
    ids = next(item for item in predicates if str(item.left).endswith(".agent_id"))
    assert set(ids.right.value) == {7, 8}
    session.commit.assert_not_called()


def test_no_binding_metadata_does_not_query_database():
    session = MagicMock()
    assert agent_db.query_binding_agent_metadata(session, [], tenant_id="t1") == {}
    session.query.assert_not_called()
