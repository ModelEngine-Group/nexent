# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Unit coverage for the knowledge-reference guard modules.

These tests exercise the shared guard plumbing without a database: the query
layer runs against a sequenced session double, and the service layer patches
its collaborators. Behavior that needs a live database (advisory locks,
cascade cleanup against real rows, the status endpoint round-trip) is covered
by the dedicated integration checks; this file keeps the branches honest.
"""

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
import backend.services.knowledge_reference_service as service  # noqa: E402
import backend.utils.knowledge_reference as reference_utils  # noqa: E402
import consts.const as const_module  # noqa: E402
import consts.error_code as error_code_module  # noqa: E402


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


def _use_session(monkeypatch, session):
    monkeypatch.setattr(reference_db, "get_db_session", lambda: _session_ctx(session))


def _use_service_session(monkeypatch, session):
    monkeypatch.setattr(service, "get_db_session", lambda: _session_ctx(session))


# ---------------------------------------------------------------------------
# database layer
# ---------------------------------------------------------------------------


def test_knowledge_tool_ids_maps_param_to_tool_rows(monkeypatch):
    session = _SequencedSession([(64,), (None,)])
    _use_session(monkeypatch, session)
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
    _use_session(monkeypatch, session)
    rows = reference_db.query_tool_instance_reference_rows(session, "aidp", {"kds-1"})
    assert [(row["agent_id"], row["version_no"], row["reference_origin"]) for row in rows] == [
        (7, 0, reference_utils.REFERENCE_ORIGIN_TOOL),
        (7, 1, reference_utils.REFERENCE_ORIGIN_TOOL),
    ]

    empty = _SequencedSession([])
    _use_session(monkeypatch, empty)
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
    _use_session(monkeypatch, session)
    rows = reference_db.query_skill_instance_reference_rows(session, "aidp", {"kds-1"})
    assert [(row["agent_id"], row["version_no"], row["reference_origin"]) for row in rows] == [
        (7, 0, reference_utils.REFERENCE_ORIGIN_SKILL),
        (7, 1, reference_utils.REFERENCE_ORIGIN_SKILL),
    ]

    no_instances = _SequencedSession([(64,)], [])
    _use_session(monkeypatch, no_instances)
    assert reference_db.query_skill_instance_reference_rows(no_instances, "aidp", {"kds-1"}) == []

    no_tools = _SequencedSession([])
    _use_session(monkeypatch, no_tools)
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
    _use_session(monkeypatch, session)
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
    _use_session(monkeypatch, empty)
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
    _use_session(monkeypatch, session)
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
    _use_session(monkeypatch, session)
    local_ref = ("local", "idx-1")
    changed = reference_db._strip_deleted_resource_from_conversation_scopes(
        session, [local_ref]
    )
    assert changed == 2
    assert scope_only.knowledge_scope["local"]["knowledge_ids"] == ["9"]
    assert workbench_only.workbench_config["knowledge_scope"]["local"]["mode"] == "inherit"

    # AIDP refs skip the knowledge-record lookup entirely.
    aidp_session = _SequencedSession([unchanged])
    _use_session(monkeypatch, aidp_session)
    assert (
        reference_db._strip_deleted_resource_from_conversation_scopes(
            aidp_session, [AIDP_REF]
        )
        == 0
    )


def test_agent_reference_metadata_and_local_record_queries(monkeypatch):
    session = _SequencedSession(
        [SimpleNamespace(agent_id=7, display_name="A", created_by="u1")],
    )
    _use_session(monkeypatch, session)
    metadata = reference_db.query_agent_reference_metadata(session, [7, 7], tenant_id="t1")
    assert metadata[7]["display_name"] == "A"
    assert reference_db.query_agent_reference_metadata(session, [], tenant_id="t1") == {}

    records_session = _SequencedSession(
        [SimpleNamespace(index_name="idx-1", knowledge_id=213), SimpleNamespace(index_name=None)],
    )
    _use_session(monkeypatch, records_session)
    records = reference_db.query_local_knowledge_records(
        records_session, ["idx-1", "idx-1"]
    )
    assert set(records) == {"idx-1"}
    assert reference_db.query_local_knowledge_records(records_session, []) == {}

    include_deleted_session = _SequencedSession([])
    _use_session(monkeypatch, include_deleted_session)
    assert (
        reference_db.query_local_knowledge_records(
            include_deleted_session, ["idx-1"], include_deleted=True
        )
        == {}
    )


def test_deleted_id_queries_and_tool_param_map(monkeypatch):
    session = _SequencedSession([("idx-1",), (None,)])
    _use_session(monkeypatch, session)
    assert reference_db.query_deleted_local_knowledge_ids(session, ["idx-1"]) == {"idx-1"}
    assert reference_db.query_deleted_local_knowledge_ids(session, []) == set()

    aidp_session = _SequencedSession([("kds-1",)])
    _use_session(monkeypatch, aidp_session)
    assert reference_db.query_deleted_aidp_kb_ids(
        aidp_session, ["kds-1"], tenant_id="t1"
    ) == {"kds-1"}
    assert reference_db.query_deleted_aidp_kb_ids(aidp_session, []) == set()

    params_session = _SequencedSession([(64, "aidp_search"), (65, "other"), (None, "aidp_search")])
    _use_session(monkeypatch, params_session)
    assert reference_db.query_knowledge_tool_params_by_ids(params_session, [64, 65]) == {
        64: "kds_list"
    }
    assert reference_db.query_knowledge_tool_params_by_ids(params_session, []) == {}


def test_acquire_lock_keys_acquires_unlocks_and_times_out(monkeypatch):
    from contextlib import contextmanager as _ctx

    @_ctx
    def _empty_ctx():
        yield

    # Empty key set: no session work at all.
    monkeypatch.setattr(reference_db, "get_db_session", _empty_ctx)
    with reference_db.acquire_lock_keys([]):
        pass

    session = _SequencedSession()
    _use_session(monkeypatch, session)
    with reference_db.acquire_lock_keys([11, 11, 22]):
        pass
    locks = [params["key"] for sql, params in session.executed if "advisory_lock" in sql]
    unlocks = [params["key"] for sql, params in session.executed if "advisory_unlock" in sql]
    assert locks == [11, 22]
    assert unlocks == [11, 22]

    busy_session = _SequencedSession()
    busy_session.execute_results = [False]
    _use_session(monkeypatch, busy_session)
    with pytest.raises(Exception) as excinfo:
        with reference_db.acquire_lock_keys([33], timeout_seconds=0.0):
            pass
    assert excinfo.value.error_code == error_code_module.ErrorCode.KNOWLEDGE_RESOURCE_BUSY

    failing_unlock = _SequencedSession()
    failing_unlock.execute_results = [True, RuntimeError("unlock failed")]
    _use_session(monkeypatch, failing_unlock)
    with reference_db.acquire_lock_keys([44]):
        pass  # the release failure is logged, not raised


# ---------------------------------------------------------------------------
# service layer
# ---------------------------------------------------------------------------


def test_visibility_context_and_agent_visibility(monkeypatch):
    monkeypatch.setattr(
        service,
        "get_user_tenant_by_user_id",
        lambda user_id: {"user_role": "ADMIN", "tenant_id": "t9"},
    )
    context = service.build_visibility_context("u1", None)
    assert context.can_edit_all is True
    assert context.tenant_id == "t9"

    monkeypatch.setattr(
        service,
        "get_user_tenant_by_user_id",
        lambda user_id: {"user_role": "DEV", "tenant_id": "t1"},
    )
    monkeypatch.setattr(service, "query_group_ids_by_user", lambda user_id: [9, "10"])
    context = service.build_visibility_context("u1", "t1")
    assert context.user_group_ids == {9, 10}
    assert service.build_visibility_context("u1", "t1").tenant_id == "t1"

    def _boom(user_id):
        raise RuntimeError("group lookup failed")

    monkeypatch.setattr(service, "query_group_ids_by_user", _boom)
    assert service.build_visibility_context("u1", "t1").user_group_ids == set()

    assert service.is_agent_visible(context, {"created_by": "u1"}) is True
    assert (
        service.is_agent_visible(
            context,
            {"created_by": "other", "tenant_id": const_module.__dict__.get("ASSET_OWNER_TENANT_ID", "asset_owner_tenant_id")},
        )
        is True
    )
    assert (
        service.is_agent_visible(
            context,
            {"created_by": "other", "tenant_id": "t1", "group_ids": "9", "ingroup_permission": "READ_ONLY"},
        )
        is True
    )
    assert (
        service.is_agent_visible(
            context,
            {"created_by": "other", "tenant_id": "t1", "group_ids": "9", "ingroup_permission": "PRIVATE"},
        )
        is False
    )
    assert (
        service.is_agent_visible(
            context,
            {"created_by": "other", "tenant_id": "t1", "group_ids": "5", "ingroup_permission": "READ_ONLY"},
        )
        is False
    )
    assert (
        service.is_agent_visible(
            SimpleNamespace(
                can_edit_all=True,
                user_id="u1",
                tenant_id="t1",
                user_role="ADMIN",
                user_group_ids=set(),
            ),
            {"created_by": "other"},
        )
        is True
    )


def test_collect_agent_reference_preview_dedupes_and_counts_hidden(monkeypatch):
    import services.knowledge_reference_service as service_module

    monkeypatch.setattr(
        service_module,
        "query_live_agent_reference_rows",
        lambda session, ref: [
            {"agent_id": 7, "version_no": 0},
            {"agent_id": 7, "version_no": 1},
            {"agent_id": 8, "version_no": 0},
        ],
    )
    monkeypatch.setattr(
        service_module,
        "query_agent_reference_metadata",
        lambda session, ids, tenant_id: {
            7: {"agent_id": 7, "display_name": "Alpha"},
            8: {"agent_id": 8, "name": "Beta"},
        },
    )
    monkeypatch.setattr(
        service_module,
        "build_visibility_context",
        lambda user_id, tenant_id=None: SimpleNamespace(
            can_edit_all=True, user_id="u1", tenant_id="t1", user_role="ADMIN", user_group_ids=set()
        ),
    )
    monkeypatch.setattr(
        service_module,
        "is_agent_visible",
        lambda context, agent: agent["agent_id"] != 8,
    )
    _use_service_session(monkeypatch, _SequencedSession())
    preview = service_module.collect_agent_reference_preview(
        [AIDP_REF], user_id="u1", tenant_id="t1"
    )
    assert preview == {
        "agents": [{"agent_id": 7, "display_name": "Alpha"}],
        "hidden_agent_count": 1,
        "total_agent_count": 2,
    }

    monkeypatch.setattr(
        service_module, "query_live_agent_reference_rows", lambda session, ref: []
    )
    empty = service_module.collect_agent_reference_preview(
        [AIDP_REF], user_id="u1", tenant_id="t1"
    )
    assert empty == {"agents": [], "hidden_agent_count": 0, "total_agent_count": 0}


def test_reject_confirmed_deleted_references(monkeypatch):
    _use_service_session(monkeypatch, _SequencedSession())
    monkeypatch.setattr(
        service, "query_deleted_local_knowledge_ids", lambda session, ids: {"idx-1"}
    )
    monkeypatch.setattr(
        service, "query_deleted_aidp_kb_ids", lambda session, ids, tenant: set()
    )
    with pytest.raises(Exception) as excinfo:
        service.reject_confirmed_deleted_knowledge_references(
            [LOCAL_REF], tenant_id="t1"
        )
    assert "idx-1" in str(excinfo.value)

    monkeypatch.setattr(
        service, "query_deleted_local_knowledge_ids", lambda session, ids: set()
    )
    monkeypatch.setattr(
        service,
        "query_deleted_aidp_kb_ids",
        lambda session, ids, tenant: {"kds-1"} if ids else set(),
    )
    with pytest.raises(Exception) as excinfo:
        service.reject_confirmed_deleted_knowledge_references(
            [AIDP_REF], tenant_id="t1"
        )
    assert "kds-1" in str(excinfo.value)

    monkeypatch.setattr(
        service, "query_deleted_aidp_kb_ids", lambda session, ids, tenant: set()
    )
    service.reject_confirmed_deleted_knowledge_references([AIDP_REF], tenant_id="t1")
    service.reject_confirmed_deleted_knowledge_references([], tenant_id="t1")


def test_remove_knowledge_references_returns_cleanup_counts(monkeypatch):
    _use_service_session(monkeypatch, _SequencedSession())
    monkeypatch.setattr(
        service,
        "strip_deleted_resource_from_bindings",
        lambda session, ref: {"tool_instances": 1, "skill_instances": 0, "conversations": 1},
    )
    counts = service.remove_knowledge_references([AIDP_REF])
    assert counts == {"tool_instances": 1, "skill_instances": 0, "conversations": 1}


def test_lock_namespace_and_guards(monkeypatch):
    monkeypatch.setattr(const_module, "AIDP_SERVER_URL", "http://AIDP:30081/")
    monkeypatch.setattr(const_module, "AIDP_TENANT_ID", "aidp")
    assert service.lock_namespace_for(AIDP_REF[0]) == "aidp:http://aidp:30081:aidp"
    assert service.lock_namespace_for(LOCAL_REF[0]) == ""
    keys = service.resource_lock_keys_for([AIDP_REF, LOCAL_REF])
    assert len(keys) == 2 and all(isinstance(key, int) for key in keys)

    from contextlib import contextmanager as _ctx

    held = []

    @_ctx
    def _record_locks(keys):
        held.append(list(keys))
        yield

    monkeypatch.setattr(service, "acquire_lock_keys", _record_locks)
    with service.knowledge_deletion_guard([AIDP_REF]):
        pass
    with service.knowledge_reference_write_guard([AIDP_REF]):
        pass
    assert len(held) == 2
# ---------------------------------------------------------------------------
# additional branch coverage
# ---------------------------------------------------------------------------


def test_skill_instance_rows_skip_incomplete_configurations(monkeypatch):
    no_skill_id = SimpleNamespace(skill_id=None, agent_id=7, config_values={})
    session = _SequencedSession([(64,)], [no_skill_id])
    _use_session(monkeypatch, session)
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
    _use_session(monkeypatch, session)
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
    _use_session(monkeypatch, session)
    # Skill exists but does not list the managed knowledge tool.
    assert reference_db.query_skill_instance_reference_rows(session, "aidp", {"kds-1"}) == []

    session = _SequencedSession(
        [(64,)],
        [missing_id, no_override],
        [SimpleNamespace(skill_id=5, config_values={})],
        [(5, 64)],
    )
    _use_session(monkeypatch, session)
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
    _use_session(monkeypatch, session)
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
    _use_session(monkeypatch, session)
    rows = reference_db.query_live_agent_reference_rows(session, [AIDP_REF])
    assert {(row["agent_id"], row["version_no"]) for row in rows} == {(7, 0)}


def test_strip_bindings_no_changes_skips_commit(monkeypatch):
    session = _SequencedSession([(64,)], [], [], [])
    _use_session(monkeypatch, session)
    counts = reference_db.strip_deleted_resource_from_bindings(session, [AIDP_REF])
    assert counts == {"tool_instances": 0, "skill_instances": 0, "conversations": 0}
    assert session.commits == 0

    no_tools = _SequencedSession([], [], [])
    _use_session(monkeypatch, no_tools)
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
    _use_session(monkeypatch, session)
    counts = reference_db.strip_deleted_resource_from_bindings(session, [AIDP_REF])
    assert counts == {"tool_instances": 0, "skill_instances": 0, "conversations": 0}


def test_local_conversation_strip_without_knowledge_id(monkeypatch):
    row = SimpleNamespace(
        knowledge_scope={"local": {"mode": "override", "knowledge_ids": ["idx-1"]}},
        workbench_config=None,
    )
    session = _SequencedSession(SimpleNamespace(knowledge_id=None), [row])
    _use_session(monkeypatch, session)
    local_ref = ("local", "idx-1")
    changed = reference_db._strip_deleted_resource_from_conversation_scopes(
        session, [local_ref]
    )
    assert changed == 1
    assert row.knowledge_scope["local"]["mode"] == "inherit"


def test_deleted_aidp_ids_without_tenant_filter(monkeypatch):
    session = _SequencedSession([])
    _use_session(monkeypatch, session)
    assert (
        reference_db.query_deleted_aidp_kb_ids(session, ["kds-1"], tenant_id=None)
        == set()
    )


def test_lock_wait_retries_until_every_key_is_held(monkeypatch):
    session = _SequencedSession()
    # First pass: key 11 acquired, key 22 not; second pass: 11 revisited, 22 acquired.
    session.execute_results = [True, False, True]
    _use_session(monkeypatch, session)
    with reference_db.acquire_lock_keys([11, 22], timeout_seconds=1.0):
        pass
    locks = [params["key"] for sql, params in session.executed if "advisory_lock" in sql]
    # The re-visit of an already held key short-circuits without another query.
    assert locks == [11, 22, 22]


def test_preview_skips_rows_without_agent_metadata(monkeypatch):
    import services.knowledge_reference_service as service_module

    monkeypatch.setattr(
        service_module,
        "query_live_agent_reference_rows",
        lambda session, ref: [{"agent_id": 7}, {"agent_id": 8}],
    )
    monkeypatch.setattr(
        service_module,
        "query_agent_reference_metadata",
        lambda session, ids, tenant_id: {7: {"agent_id": 7, "display_name": "Alpha"}},
    )
    monkeypatch.setattr(
        service_module,
        "build_visibility_context",
        lambda user_id, tenant_id=None: SimpleNamespace(
            can_edit_all=True,
            user_id="u1",
            tenant_id="t1",
            user_role="ADMIN",
            user_group_ids=set(),
        ),
    )
    monkeypatch.setattr(service_module, "is_agent_visible", lambda context, agent: True)
    _use_service_session(monkeypatch, _SequencedSession())
    preview = service_module.collect_agent_reference_preview(
        [AIDP_REF], user_id="u1", tenant_id="t1"
    )
    assert preview["agents"] == [{"agent_id": 7, "display_name": "Alpha"}]
    assert preview["total_agent_count"] == 1


def test_remove_knowledge_references_without_changes_skips_logging(monkeypatch):
    _use_service_session(monkeypatch, _SequencedSession())
    monkeypatch.setattr(
        service,
        "strip_deleted_resource_from_bindings",
        lambda session, ref: {
            "tool_instances": 0,
            "skill_instances": 0,
            "conversations": 0,
        },
    )
    counts = service.remove_knowledge_references([AIDP_REF])
    assert all(value == 0 for value in counts.values())
