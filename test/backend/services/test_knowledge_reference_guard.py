# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Unit coverage for bound-agent queries and cascade cleanup with session doubles."""

import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import backend.database.knowledge_reference_db as reference_db  # noqa: E402
import backend.database.knowledge_reference_db as reference_utils  # noqa: E402


AIDP_REF = ("aidp", "kds-1")
LOCAL_REF = ("local", "idx-1")


class _SequencedSession:
    """Session double: every ``session.query`` call returns the next queued result."""

    def __init__(self, *results):
        self._results = list(results)
        self.commits = 0
        self.executed = []
        self.execute_results = []

    def query(self, *_args, **_kwargs):
        if not self._results:
            raise AssertionError("unexpected extra session.query call")
        result = self._results.pop(0)
        chain = MagicMock()
        chain.filter.return_value = chain
        chain.order_by.return_value = chain
        if isinstance(result, list):
            chain.all.return_value = result
            chain.first.return_value = result[0] if result else None
        else:
            chain.all.return_value = [result]
            chain.first.return_value = result
        return chain

    def execute(self, statement, params=None):
        self.executed.append((str(statement), dict(params or {})))
        value = self.execute_results.pop(0) if self.execute_results else True
        if isinstance(value, Exception):
            raise value
        result = MagicMock()
        result.scalar.return_value = value
        return result

    def commit(self):
        self.commits += 1


@contextmanager
def _session_ctx(session):
    yield session


@pytest.fixture(autouse=True)
def _patch_as_dict(monkeypatch):
    monkeypatch.setattr(
        reference_db,
        "as_dict",
        lambda obj: obj.__dict__ if hasattr(obj, "__dict__") else obj,
    )


# ---------------------------------------------------------------------------
# database layer
# ---------------------------------------------------------------------------


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
    assert reference_db._parse_knowledge_ids(value) == expected


def test_knowledge_tool_ids_maps_param_to_tool_rows(monkeypatch):
    session = _SequencedSession([(64,), (None,)])
    assert reference_db._knowledge_tool_ids(session, "kds_list") == {64}
    # An unmapped param never queries the tool table.
    assert reference_db._knowledge_tool_ids(session, "unknown_param") == set()


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
    rows = reference_db.query_tool_instance_reference_rows(session, "aidp", {"kds-1"})
    assert [(row["agent_id"], row["version_no"], row["reference_origin"]) for row in rows] == [
        (7, 0, reference_utils.REFERENCE_ORIGIN_TOOL),
        (7, 1, reference_utils.REFERENCE_ORIGIN_TOOL),
    ]

    empty = _SequencedSession([])
    # No mapped tool rows -> no instance query at all.
    assert reference_db.query_tool_instance_reference_rows(empty, "aidp", {"kds-1"}) == []


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
    rows = reference_db.query_skill_instance_reference_rows(session, "aidp", {"kds-1"})
    assert [(row["agent_id"], row["version_no"], row["reference_origin"]) for row in rows] == [
        (7, 0, reference_utils.REFERENCE_ORIGIN_SKILL),
        (7, 1, reference_utils.REFERENCE_ORIGIN_SKILL),
    ]

    no_instances = _SequencedSession([(64,)], [])
    assert reference_db.query_skill_instance_reference_rows(no_instances, "aidp", {"kds-1"}) == []

    no_tools = _SequencedSession([])
    assert reference_db.query_skill_instance_reference_rows(no_tools, "aidp", {"kds-1"}) == []


def test_reference_rows_dedupe_and_drop_missing_agent(monkeypatch):
    monkeypatch.setattr(
        reference_db,
        "query_tool_instance_reference_rows",
        lambda session, provider, resource_ids: [
            {"agent_id": 7, "version_no": 0, "reference_origin": "tool"},
            {"agent_id": 7, "version_no": 0, "reference_origin": "tool"},
            {"agent_id": None, "version_no": 0, "reference_origin": "tool"},
        ],
    )
    monkeypatch.setattr(
        reference_db,
        "query_skill_instance_reference_rows",
        lambda session, provider, resource_ids: [
            {"agent_id": 7, "version_no": 0, "reference_origin": "skill"},
            {"agent_id": 7, "version_no": 1, "reference_origin": "skill"},
        ],
    )
    rows = reference_db.query_reference_rows(object(), [AIDP_REF])
    keys = {
        (row["agent_id"], row["version_no"], row["reference_origin"]) for row in rows
    }
    assert keys == {(7, 0, "tool"), (7, 0, "skill"), (7, 1, "skill")}


def test_live_agent_reference_rows_filters_deleted_versions(monkeypatch):
    monkeypatch.setattr(
        reference_db,
        "query_reference_rows",
        lambda session, ref: [
            {"agent_id": 7, "version_no": 0, "reference_origin": "tool"},
            {"agent_id": 7, "version_no": 1, "reference_origin": "tool"},
            {"agent_id": 8, "version_no": 0, "reference_origin": "tool"},
            {"agent_id": 9, "version_no": 1, "reference_origin": "tool"},
        ],
    )
    session = _SequencedSession([(7, 0), (7, 1), (8, 0)])
    session.execute_results = []
    # AgentVersion query: version 1 of agent 9 was deleted, agent 7's stayed.
    session._results = [[(7, 0), (7, 1), (8, 0)], [(7, 1)]]
    rows = reference_db.query_live_agent_reference_rows(session, [AIDP_REF])
    keys = {(row["agent_id"], row["version_no"]) for row in rows}
    assert keys == {(7, 0), (7, 1), (8, 0)}

    empty = _SequencedSession([])
    monkeypatch.setattr(
        reference_db, "query_reference_rows", lambda session, ref: []
    )
    assert reference_db.query_live_agent_reference_rows(empty, [AIDP_REF]) == []


def test_strip_scope_ids_falls_back_to_inherit_when_emptied():
    scope = {
        "schema_version": 1,
        "aidp": {"mode": "override", "kds_ids": ["kds-1"]},
        "local": {"mode": "inherit", "knowledge_ids": []},
    }
    updated, changed = reference_db._strip_scope_ids(scope, "aidp", {"kds-1"})
    assert changed is True
    assert updated["aidp"] == {"mode": "inherit", "kds_ids": []}
    assert scope["aidp"]["mode"] == "override"  # original untouched

    kept, changed = reference_db._strip_scope_ids(
        {"aidp": {"mode": "override", "kds_ids": ["kds-1", "kds-2"]}},
        "aidp",
        {"kds-1"},
    )
    assert changed is True
    assert kept["aidp"] == {"mode": "override", "kds_ids": ["kds-2"]}

    assert reference_db._strip_scope_ids("nope", "aidp", {"kds-1"}) == ("nope", False)
    assert reference_db._strip_scope_ids({"local": 1}, "local", {"x"})[1] is False
    assert reference_db._strip_scope_ids(
        {"aidp": {"kds_ids": "not-a-list"}}, "aidp", {"kds-1"}
    )[1] is False
    assert reference_db._strip_scope_ids(
        {"aidp": {"mode": "inherit", "kds_ids": ["kds-9"]}}, "aidp", {"kds-1"}
    )[1] is False


def test_strip_deleted_resource_from_bindings_cleans_all_three_stores(monkeypatch):
    tool_list = SimpleNamespace(
        agent_id=7,
        version_no=0,
        params={"kds_list": ["kds-1", "kds-2"], "display_names": ["A", "B"]},
    )
    tool_json = SimpleNamespace(
        agent_id=7,
        version_no=1,
        params={"kds_list": '["kds-1"]'},
    )
    untouched_tool = SimpleNamespace(
        agent_id=8, version_no=0, params={"kds_list": ["kds-9"]}
    )
    skill_instance = SimpleNamespace(
        skill_id=5, config_values={"kds_list": ["kds-1", "kds-3"]}
    )
    conversation = SimpleNamespace(
        knowledge_scope={
            "schema_version": 1,
            "aidp": {"mode": "override", "kds_ids": ["kds-1", "kds-2"]},
        },
        workbench_config=None,
    )
    session = _SequencedSession(
        [(64,)],
        [tool_list, tool_json, untouched_tool],
        [skill_instance],
        [conversation],
    )
    counts = reference_db.strip_deleted_resource_from_bindings(session, [AIDP_REF])
    assert counts == {"tool_instances": 2, "skill_instances": 1, "conversations": 1}
    assert session.commits == 0
    assert tool_list.params["kds_list"] == ["kds-2"]
    assert tool_list.params["display_names"] == ["B"]
    assert tool_json.params["kds_list"] == "[]"
    assert untouched_tool.params["kds_list"] == ["kds-9"]
    assert skill_instance.config_values["kds_list"] == ["kds-3"]
    assert conversation.knowledge_scope["aidp"]["kds_ids"] == ["kds-2"]


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
    local_ref = ("local", "idx-1")
    changed = reference_db._strip_deleted_resource_from_conversation_scopes(
        session, [local_ref]
    )
    assert changed == 2
    assert scope_only.knowledge_scope["local"]["knowledge_ids"] == ["9"]
    assert workbench_only.workbench_config["knowledge_scope"]["local"]["mode"] == "inherit"

    # AIDP refs skip the knowledge-record lookup entirely.
    aidp_session = _SequencedSession([unchanged])
    assert (
        reference_db._strip_deleted_resource_from_conversation_scopes(
            aidp_session, [AIDP_REF]
        )
        == 0
    )


# ---------------------------------------------------------------------------
# service layer
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# additional branch coverage
# ---------------------------------------------------------------------------


def test_skill_instance_rows_skip_incomplete_configurations(monkeypatch):
    no_skill_id = SimpleNamespace(skill_id=None, agent_id=7, config_values={})
    session = _SequencedSession([(64,)], [no_skill_id])
    # No usable skill ids at all -> early return.
    assert reference_db.query_skill_instance_reference_rows(session, "aidp", {"kds-1"}) == []

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
    rows = reference_db.query_skill_instance_reference_rows(session, "aidp", {"kds-1"})
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
    assert reference_db.query_skill_instance_reference_rows(session, "aidp", {"kds-1"}) == []

    session = _SequencedSession(
        [(64,)],
        [missing_id, no_override],
        [SimpleNamespace(skill_id=5, config_values={})],
        [(5, 64)],
    )
    # Tool is listed, but neither the override nor the template holds the id.
    assert reference_db.query_skill_instance_reference_rows(session, "aidp", {"kds-1"}) == []


def test_live_rows_draft_only_skips_version_query(monkeypatch):
    monkeypatch.setattr(
        reference_db,
        "query_reference_rows",
        lambda session, ref: [
            {"agent_id": 7, "version_no": 0, "reference_origin": "tool"},
        ],
    )
    session = _SequencedSession([(7, 0)])
    rows = reference_db.query_live_agent_reference_rows(session, [AIDP_REF])
    assert {(row["agent_id"], row["version_no"]) for row in rows} == {(7, 0)}
    assert len(session._results) == 0  # the AgentVersion query never ran


def test_live_rows_drop_versions_missing_from_the_version_table(monkeypatch):
    monkeypatch.setattr(
        reference_db,
        "query_reference_rows",
        lambda session, ref: [
            {"agent_id": 7, "version_no": 0, "reference_origin": "tool"},
            {"agent_id": 7, "version_no": 1, "reference_origin": "tool"},
        ],
    )
    session = _SequencedSession([(7, 0), (7, 1)], [])
    rows = reference_db.query_live_agent_reference_rows(session, [AIDP_REF])
    assert {(row["agent_id"], row["version_no"]) for row in rows} == {(7, 0)}


def test_strip_bindings_no_changes_skips_commit(monkeypatch):
    session = _SequencedSession([(64,)], [], [], [])
    counts = reference_db.strip_deleted_resource_from_bindings(session, [AIDP_REF])
    assert counts == {"tool_instances": 0, "skill_instances": 0, "conversations": 0}
    assert session.commits == 0

    no_tools = _SequencedSession([], [], [])
    assert reference_db.strip_deleted_resource_from_bindings(no_tools, [AIDP_REF]) == {
        "tool_instances": 0,
        "skill_instances": 0,
        "conversations": 0,
    }


def test_strip_bindings_ignores_malformed_entries(monkeypatch):
    bad_params = SimpleNamespace(agent_id=7, version_no=0, params="nope")
    bad_skill_config = SimpleNamespace(skill_id=5, config_values=["nope"])
    unrelated_skill_config = SimpleNamespace(
        skill_id=6, config_values={"kds_list": ["kds-9"]}
    )
    session = _SequencedSession(
        [(64,)],
        [bad_params],
        [bad_skill_config, unrelated_skill_config],
        [],
    )
    counts = reference_db.strip_deleted_resource_from_bindings(session, [AIDP_REF])
    assert counts == {"tool_instances": 0, "skill_instances": 0, "conversations": 0}


def test_local_conversation_strip_without_knowledge_id(monkeypatch):
    row = SimpleNamespace(
        knowledge_scope={"local": {"mode": "override", "knowledge_ids": ["idx-1"]}},
        workbench_config=None,
    )
    session = _SequencedSession(SimpleNamespace(knowledge_id=None), [row])
    local_ref = ("local", "idx-1")
    changed = reference_db._strip_deleted_resource_from_conversation_scopes(
        session, [local_ref]
    )
    assert changed == 1
    assert row.knowledge_scope["local"]["mode"] == "inherit"
