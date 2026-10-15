# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import database.tool_db as tool_db


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
    monkeypatch.setattr(tool_db, "as_dict", vars)


@pytest.mark.parametrize("value,expected", [
    (["idx-1", "idx-1", "idx-2"], ["idx-1", "idx-2"]),
    ('["kds-1", "kds-2"]', ["kds-1", "kds-2"]),
    ([213, "213"], ["213"]),
    ("idx-1,idx-2", []),
    ('"kds-1"', []),
    ({"kds_id": "kds-1"}, []),
    ([False, {}, ""], []),
])
def test_binding_ids_use_selector_arrays_and_json_arrays(value, expected):
    assert tool_db.parse_knowledge_selection(value) == expected


def test_knowledge_tool_ids_maps_param_to_tool_rows(monkeypatch):
    session = _SequencedSession([(64,), (None,)])
    assert tool_db.query_knowledge_tool_ids(session, "kds_list") == {64}
    # An unmapped param never queries the tool table.
    assert tool_db.query_knowledge_tool_ids(session, "unknown_param") == set()


def test_tool_instance_rows_parse_list_and_json_params(monkeypatch):
    matching_list = SimpleNamespace(
        agent_id=7, version_no=0, params={"kds_list": ["kds-1"]}
    )
    matching_json = SimpleNamespace(
        agent_id=7, version_no=1, params={"kds_list": '["kds-1", "kds-2"]'}
    )
    other_id = SimpleNamespace(agent_id=8, version_no=0, params={"kds_list": ["kds-9"]})
    bad_params = SimpleNamespace(agent_id=9, version_no=0, params="nope")
    session = _SequencedSession(
        [(64,)],
        [matching_list, matching_json, other_id, bad_params],
    )
    rows = tool_db.query_tool_knowledge_bindings(session, "kds_list", {"kds-1"})
    assert [(row["agent_id"], row["version_no"]) for row in rows] == [
        (7, 0),
        (7, 1),
    ]

    empty = _SequencedSession([])
    # No mapped tool rows -> no instance query at all.
    assert tool_db.query_tool_knowledge_bindings(empty, "kds_list", {"kds-1"}) == []
