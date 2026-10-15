# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import database.conversation_db as conversation_db


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
    monkeypatch.setattr(conversation_db, "as_dict", vars)


def test_strip_scope_ids_falls_back_to_inherit_when_emptied():
    scope = {
        "schema_version": 1,
        "aidp": {"mode": "override", "kds_ids": ["kds-1"]},
        "local": {"mode": "inherit", "knowledge_ids": []},
    }
    updated, changed = conversation_db._strip_scope_ids(scope, "aidp", {"kds-1"})
    assert changed is True
    assert updated["aidp"] == {"mode": "inherit", "kds_ids": []}
    assert scope["aidp"]["mode"] == "override"  # original untouched

    kept, changed = conversation_db._strip_scope_ids(
        {"aidp": {"mode": "override", "kds_ids": ["kds-1", "kds-2"]}},
        "aidp",
        {"kds-1"},
    )
    assert changed is True
    assert kept["aidp"] == {"mode": "override", "kds_ids": ["kds-2"]}

    assert conversation_db._strip_scope_ids("nope", "kds_list", {"kds-1"}) == ("nope", False)
    assert conversation_db._strip_scope_ids({"local": 1}, "local", {"x"})[1] is False
    assert conversation_db._strip_scope_ids(
        {"aidp": {"kds_ids": "not-a-list"}}, "kds_list", {"kds-1"}
    )[1] is False
    assert conversation_db._strip_scope_ids(
        {"aidp": {"mode": "inherit", "kds_ids": ["kds-9"]}}, "kds_list", {"kds-1"}
    )[1] is False


def test_strip_conversation_scopes_handles_workbench_copy_and_local_ids(monkeypatch):
    scope_only = SimpleNamespace(
        knowledge_scope={
            "local": {"mode": "override", "knowledge_ids": ["213", "9"]},
        },
        workbench_config=None,
    )
    workbench_only = SimpleNamespace(
        knowledge_scope={"local": {"mode": "inherit", "knowledge_ids": []}},
        workbench_config={
            "knowledge_scope": {
                "local": {"mode": "override", "knowledge_ids": ["213"]},
            }
        },
    )
    unchanged = SimpleNamespace(
        knowledge_scope={"local": {"mode": "override", "knowledge_ids": ["9"]}},
        workbench_config={},
    )
    session = _SequencedSession(
        SimpleNamespace(knowledge_id=213),
        [scope_only, workbench_only, unchanged],
    )
    changed = conversation_db.remove_conversation_knowledge_bindings(
        session, index_names=["idx-1"]
    )
    assert changed == 2
    assert scope_only.knowledge_scope["local"]["knowledge_ids"] == ["9"]
    assert workbench_only.workbench_config["knowledge_scope"]["local"]["mode"] == "inherit"

    # AIDP refs skip the knowledge-record lookup entirely.
    aidp_session = _SequencedSession([unchanged])
    assert (
        conversation_db.remove_conversation_knowledge_bindings(
            aidp_session, kds_ids=["kds-1"]
        )
        == 0
    )


def test_local_conversation_strip_without_knowledge_id(monkeypatch):
    row = SimpleNamespace(
        knowledge_scope={"local": {"mode": "override", "knowledge_ids": ["idx-1"]}},
        workbench_config=None,
    )
    session = _SequencedSession(SimpleNamespace(knowledge_id=None), [row])
    changed = conversation_db.remove_conversation_knowledge_bindings(
        session, index_names=["idx-1"]
    )
    assert changed == 1
    assert row.knowledge_scope["local"]["mode"] == "inherit"
