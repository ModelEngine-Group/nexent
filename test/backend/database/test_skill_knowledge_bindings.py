# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import database.skill_db as skill_db


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
    monkeypatch.setattr(skill_db, "as_dict", vars)


def test_skill_instance_rows_follow_template_and_instance_overrides(monkeypatch):
    from_override = SimpleNamespace(
        skill_id=5, agent_id=7, version_no=0, config_values={"kds_list": ["kds-1"]}
    )
    from_template = SimpleNamespace(
        skill_id=5, agent_id=7, version_no=1, config_values={}
    )
    orphan_skill = SimpleNamespace(
        skill_id=6, agent_id=8, version_no=0, config_values={"kds_list": ["kds-1"]}
    )
    session = _SequencedSession(
        [(64,)],
        [from_override, from_template, orphan_skill],
        [SimpleNamespace(skill_id=5, config_values={"kds_list": ["kds-1"]})],
        [(5, 64)],
    )
    rows = skill_db.query_skill_knowledge_bindings(session, "kds_list", {"kds-1"})
    assert [(row["agent_id"], row["version_no"]) for row in rows] == [
        (7, 0),
        (7, 1),
    ]

    no_instances = _SequencedSession([(64,)], [])
    assert skill_db.query_skill_knowledge_bindings(no_instances, "kds_list", {"kds-1"}) == []

    no_tools = _SequencedSession([])
    assert skill_db.query_skill_knowledge_bindings(no_tools, "kds_list", {"kds-1"}) == []


def test_skill_instance_rows_skip_incomplete_configurations(monkeypatch):
    no_skill_id = SimpleNamespace(skill_id=None, agent_id=7, config_values={})
    session = _SequencedSession([(64,)], [no_skill_id])
    # No usable skill ids at all -> early return.
    assert skill_db.query_skill_knowledge_bindings(session, "kds_list", {"kds-1"}) == []

    matching = SimpleNamespace(
        skill_id=5, agent_id=7, version_no=0, config_values={"kds_list": ["kds-1"]}
    )
    session = _SequencedSession(
        [(64,)],
        [no_skill_id, matching],
        [SimpleNamespace(skill_id=5, config_values={})],
        [(5, 64)],
    )
    # The orphan instance is skipped, the matching one resolves.
    rows = skill_db.query_skill_knowledge_bindings(session, "kds_list", {"kds-1"})
    assert [(row["agent_id"], row["version_no"]) for row in rows] == [(7, 0)]

    missing_id = SimpleNamespace(
        skill_id=5, agent_id=7, version_no=0, config_values={"kds_list": ["kds-9"]}
    )
    no_override = SimpleNamespace(skill_id=5, agent_id=7, version_no=0, config_values={})
    session = _SequencedSession(
        [(64,)],
        [matching, missing_id, no_override],
        [SimpleNamespace(skill_id=5, config_values={})],
        [(5, 999)],
    )
    # Skill exists but does not list the managed knowledge tool.
    assert skill_db.query_skill_knowledge_bindings(session, "kds_list", {"kds-1"}) == []

    session = _SequencedSession(
        [(64,)],
        [missing_id, no_override],
        [SimpleNamespace(skill_id=5, config_values={})],
        [(5, 64)],
    )
    # Tool is listed, but neither the override nor the template holds the id.
    assert skill_db.query_skill_knowledge_bindings(session, "kds_list", {"kds-1"}) == []
