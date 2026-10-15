# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Diff-coverage companions for the knowledge-reference feature.

Covers the HTTP handlers of the status/preview API, the skill-side reference
resolution, the conversation scope merge helpers, and the configured-scope
baseline. Everything is exercised through module-level patches, matching the
style of the neighboring suites.
"""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import apps.knowledge_reference_app as ref_app  # noqa: E402
import consts.error_code as error_code_module  # noqa: E402
import database.client as db_client  # noqa: E402
import database.knowledge_reference_db as reference_db  # noqa: E402
import management.services.skill.service as skill_service_module  # noqa: E402
import services.conversation_management_service as conversation_service  # noqa: E402
import services.knowledge_scope_service as scope_service  # noqa: E402
from consts.model import (  # noqa: E402
    KnowledgeReferencePreviewRequest,
    KnowledgeResourceStatusItem,
    KnowledgeResourceStatusRequest,
)


def _run(coro):
    return asyncio.run(coro)


def _body(response):
    return json.loads(response.body.decode("utf-8"))


# ---------------------------------------------------------------------------
# HTTP handlers
# ---------------------------------------------------------------------------


@pytest.fixture()
def _app_patches(monkeypatch):
    monkeypatch.setattr(ref_app, "get_current_user_id", lambda auth: ("u1", "t1"))
    monkeypatch.setattr(
        ref_app,
        "resolve_item_statuses",
        lambda refs, user_id, tenant_id, vdb_core=None: [
            {"provider": ref.provider, "resource_id": ref.resource_id, "status": "available"}
            for ref in refs
        ],
    )
    monkeypatch.setattr(
        ref_app,
        "collect_agent_reference_preview",
        lambda ref, user_id, tenant_id=None: {
            "agents": [{"agent_id": 7, "display_name": "Alpha"}],
            "hidden_agent_count": 0,
            "total_agent_count": 1,
        },
    )
    monkeypatch.setattr(ref_app, "assert_agent_context_visible", lambda *a, **k: None)
    monkeypatch.setattr(ref_app, "get_conversation", lambda *a, **k: {"conversation_id": 5})
    monkeypatch.setattr(ref_app, "get_vector_db_core", lambda: SimpleNamespace())


def _status_request(items, context=None):
    return KnowledgeResourceStatusRequest(
        items=[KnowledgeResourceStatusItem(provider=p, resource_id=r) for p, r in items],
        context=context,
    )


def test_status_endpoint_returns_items(_app_patches):
    response = _run(
        ref_app.query_knowledge_resource_statuses(
            _status_request([("aidp", "kds-1"), ("local", "idx-1")]), authorization="Bearer x"
        )
    )
    assert response.status_code == 200
    payload = _body(response)
    assert [item["resource_id"] for item in payload["items"]] == ["kds-1", "idx-1"]


def test_status_endpoint_validates_inputs(_app_patches):
    with pytest.raises(Exception) as excinfo:
        _run(
            ref_app.query_knowledge_resource_statuses(
                _status_request([("aidp", "x")] * 101), authorization=None
            )
        )
    assert excinfo.value.error_code == error_code_module.ErrorCode.COMMON_VALIDATION_ERROR

    with pytest.raises(Exception) as excinfo:
        _run(
            ref_app.query_knowledge_resource_statuses(
                _status_request([("weird", "x")]), authorization=None
            )
        )
    assert excinfo.value.error_code == error_code_module.ErrorCode.COMMON_VALIDATION_ERROR

    with pytest.raises(Exception) as excinfo:
        _run(
            ref_app.query_knowledge_resource_statuses(
                _status_request([("aidp", "x")], context={"type": "agent"}), authorization=None
            )
        )
    assert excinfo.value.error_code == error_code_module.ErrorCode.COMMON_VALIDATION_ERROR

    with pytest.raises(Exception) as excinfo:
        _run(
            ref_app.query_knowledge_resource_statuses(
                _status_request([("aidp", "x")], context={"type": "conversation"}),
                authorization=None,
            )
        )
    assert excinfo.value.error_code == error_code_module.ErrorCode.COMMON_VALIDATION_ERROR

    with pytest.raises(Exception) as excinfo:
        _run(
            ref_app.query_knowledge_resource_statuses(
                _status_request([("aidp", "x")], context={"type": "bogus"}),
                authorization=None,
            )
        )
    assert excinfo.value.error_code == error_code_module.ErrorCode.COMMON_VALIDATION_ERROR


def test_status_endpoint_checks_context_visibility(_app_patches, monkeypatch):
    monkeypatch.setattr(ref_app, "get_conversation", lambda *a, **k: None)
    with pytest.raises(Exception) as excinfo:
        _run(
            ref_app.query_knowledge_resource_statuses(
                _status_request([("aidp", "x")], context={"type": "conversation", "conversation_id": 5}),
                authorization=None,
            )
        )
    assert excinfo.value.error_code == error_code_module.ErrorCode.COMMON_RESOURCE_NOT_FOUND


def test_status_endpoint_survives_missing_vector_core(_app_patches, monkeypatch):
    def _broken():
        raise RuntimeError("es unavailable")

    monkeypatch.setattr(ref_app, "get_vector_db_core", _broken)
    response = _run(
        ref_app.query_knowledge_resource_statuses(
            _status_request([("local", "idx-1")], context={"type": "agent", "agent_id": 7}),
            authorization=None,
        )
    )
    assert response.status_code == 200


def test_preview_endpoint_returns_agents(_app_patches):
    response = _run(
        ref_app.query_knowledge_reference_preview(
            KnowledgeReferencePreviewRequest(provider="aidp", resource_id="kds-1"),
            authorization="Bearer x",
        )
    )
    assert response.status_code == 200
    assert _body(response)["agents"] == [{"agent_id": 7, "display_name": "Alpha"}]


def test_preview_endpoint_validates_and_checks_access(_app_patches, monkeypatch):
    with pytest.raises(Exception) as excinfo:
        _run(
            ref_app.query_knowledge_reference_preview(
                KnowledgeReferencePreviewRequest(provider="weird", resource_id="x"),
                authorization=None,
            )
        )
    assert excinfo.value.error_code == error_code_module.ErrorCode.COMMON_VALIDATION_ERROR

    monkeypatch.setattr(
        ref_app,
        "resolve_item_statuses",
        lambda refs, user_id, tenant_id, vdb_core=None: [
            {"provider": "aidp", "resource_id": "kds-1", "status": "not_found"}
        ],
    )
    with pytest.raises(Exception) as excinfo:
        _run(
            ref_app.query_knowledge_reference_preview(
                KnowledgeReferencePreviewRequest(provider="aidp", resource_id="kds-1"),
                authorization=None,
            )
        )
    assert excinfo.value.error_code == error_code_module.ErrorCode.COMMON_FORBIDDEN


# ---------------------------------------------------------------------------
# skill-side reference resolution
# ---------------------------------------------------------------------------


def _patch_skill_db(monkeypatch, skill):
    monkeypatch.setattr(
        skill_service_module.skill_db, "get_skill_by_id", lambda skill_id, tenant_id: skill
    )
    from contextlib import contextmanager

    @contextmanager
    def _session():
        yield object()

    monkeypatch.setattr(db_client, "get_db_session", _session)


def test_skill_knowledge_references_resolution(monkeypatch):
    resolve = skill_service_module.SkillService._skill_knowledge_references

    monkeypatch.setattr(
        skill_service_module.skill_db, "get_skill_by_id", lambda *a, **k: None
    )
    assert resolve(SimpleNamespace(skill_id=None, config_values={}), "t1") == []
    assert resolve(SimpleNamespace(skill_id=5, config_values={}), "t1") == []

    monkeypatch.setattr(
        skill_service_module.skill_db,
        "get_skill_by_id",
        lambda *a, **k: {"skill_id": 5, "tool_ids": [], "config_values": {}},
    )
    assert resolve(SimpleNamespace(skill_id=5, config_values={}), "t1") == []

    monkeypatch.setattr(
        skill_service_module.skill_db,
        "get_skill_by_id",
        lambda *a, **k: {"skill_id": 5, "tool_ids": [64], "config_values": {}},
    )
    monkeypatch.setattr(
        reference_db, "query_knowledge_tool_params_by_ids", lambda session, ids: {}
    )
    assert resolve(SimpleNamespace(skill_id=5, config_values={"kds_list": ["kds-1"]}), "t1") == []

    monkeypatch.setattr(
        reference_db, "query_knowledge_tool_params_by_ids", lambda session, ids: {64: "kds_list"}
    )
    monkeypatch.setattr(
        skill_service_module.skill_db,
        "get_skill_by_id",
        lambda *a, **k: {
            "skill_id": 5,
            "tool_ids": [64],
            "config_values": {"kds_list": ["kds-1"], "index_names": ["idx-1"]},
        },
    )
    refs = resolve(
        SimpleNamespace(skill_id=5, config_values={"kds_list": ["kds-2", "kds-2"]}), "t1"
    )
    # Template ids and per-instance overrides merge; the local param is not a
    # knowledge param for this tool map and drops out.
    assert [(ref.provider, ref.resource_id) for ref in refs] == [("aidp", "kds-2")]


# ---------------------------------------------------------------------------
# conversation scope helpers
# ---------------------------------------------------------------------------


def test_scope_ids_for_source_variants():
    assert conversation_service._scope_ids_for_source(None, "local") == []
    assert conversation_service._scope_ids_for_source({"local": "x"}, "local") == []
    assert (
        conversation_service._scope_ids_for_source(
            {"local": {"mode": "inherit", "knowledge_ids": ["1"]}}, "local"
        )
        == []
    )
    assert conversation_service._scope_ids_for_source(
        {"local": {"mode": "override", "knowledge_ids": [213, "9"]}}, "local"
    ) == ["213", "9"]
    assert conversation_service._scope_ids_for_source(
        {"aidp": {"mode": "override", "kds_ids": ["kds-1"]}}, "aidp"
    ) == ["kds-1"]


def test_previous_selected_ids_prefers_override_then_configured(monkeypatch):
    conversation = {"agent_id": None, "knowledge_scope": {"local": {"mode": "override", "knowledge_ids": ["1"]}}}
    previous = conversation_service._previous_selected_ids(conversation, {}, "t1")
    assert previous == {"local": ["1"], "aidp": []}

    conversation = {"agent_id": 7, "knowledge_scope": {"aidp": {"mode": "override", "kds_ids": ["kds-1"]}}}
    monkeypatch.setattr(
        scope_service,
        "get_configured_scope_ids",
        lambda agent_id, tenant_id, version_no=None, is_debug=False: {
            "local": ["213"],
            "aidp": ["kds-9"],
        },
    )
    previous = conversation_service._previous_selected_ids(conversation, {}, "t1")
    # The local branch had no stored override -> falls back to configured ids;
    # the aidp override keeps its own ids.
    assert previous["local"] == ["213"]
    assert previous["aidp"] == ["kds-1"]

    def _broken(**kwargs):
        raise RuntimeError("tree walk failed")

    monkeypatch.setattr(scope_service, "get_configured_scope_ids", _broken)
    previous = conversation_service._previous_selected_ids(conversation, {}, "t1")
    assert previous["local"] == []
    assert previous["aidp"] == ["kds-1"]


def test_blocking_unavailable_sources_rules():
    requested = {"aidp": {"mode": "override", "kds_ids": ["kds-1", "kds-2"]}}
    # A newly added id that is explicitly unavailable blocks the save.
    blocking = conversation_service._blocking_unavailable_sources(
        [{"source": "aidp", "resource_ids": ["kds-2"]}],
        {"aidp": ["kds-1"]},
        requested,
    )
    assert blocking == ["aidp"]
    # Already selected unavailable ids do not block.
    blocking = conversation_service._blocking_unavailable_sources(
        [{"source": "aidp", "resource_ids": ["kds-1"]}],
        {"aidp": ["kds-1"]},
        requested,
    )
    assert blocking == []
    # Payloads without resource ids fall back to the source-level guard.
    blocking = conversation_service._blocking_unavailable_sources(
        [{"source": "aidp"}], {"aidp": ["kds-1"]}, requested
    )
    assert blocking == ["aidp"]
    blocking = conversation_service._blocking_unavailable_sources(
        [{"source": "aidp"}], {"aidp": ["kds-1", "kds-2"]}, requested
    )
    assert blocking == []


# ---------------------------------------------------------------------------
# configured scope baseline
# ---------------------------------------------------------------------------


def test_get_configured_scope_ids_maps_index_names(monkeypatch):
    monkeypatch.setattr(scope_service, "resolve_root_version", lambda *a, **k: 1)
    monkeypatch.setattr(
        scope_service,
        "_walk_agent_tree",
        lambda agent_id, tenant_id, version_no: [
            {
                "tools": [
                    {"class_name": "KnowledgeBaseSearchTool", "params": [{"name": "index_names", "default": ["idx-1", "idx-2"]}]},
                    {"class_name": "AidpSearchTool", "params": [{"name": "kds_list", "default": ["kds-1"]}]},
                    {"class_name": "OtherTool", "params": []},
                ]
            }
        ],
    )
    monkeypatch.setattr(
        scope_service,
        "get_knowledge_info_by_tenant_id",
        lambda tenant_id: [
            {"index_name": "idx-1", "knowledge_id": 213},
            {"index_name": "idx-2", "knowledge_id": None},
        ],
    )
    configured = scope_service.get_configured_scope_ids(7, "t1")
    assert configured == {"local": ["213"], "aidp": ["kds-1"]}
