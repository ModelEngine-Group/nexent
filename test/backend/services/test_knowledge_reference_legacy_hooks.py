# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Diff-coverage companions for the legacy-service knowledge hooks.

Covers the skill-instance write guard, the conversation scope update service
branches, and the knowledge-scope resolvers, using module-level patches in the
style of the neighboring suites.
"""

import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import database.skill_db as skill_db_module  # noqa: E402
import management.services.skill.service as skill_service_module  # noqa: E402
import services.conversation_management_service as conversation_service  # noqa: E402
import services.knowledge_reference_service as ref_service  # noqa: E402
import services.knowledge_scope_service as scope_service  # noqa: E402
from consts.exceptions import ValidationError  # noqa: E402


# ---------------------------------------------------------------------------
# skill instance write guard
# ---------------------------------------------------------------------------


def test_skill_instance_creation_guards_knowledge_references(monkeypatch):
    guard_calls = []
    reject_calls = []

    @contextmanager
    def _guard(refs):
        guard_calls.append(list(refs))
        yield

    monkeypatch.setattr(ref_service, "knowledge_reference_write_guard", _guard)
    monkeypatch.setattr(
        ref_service,
        "reject_confirmed_deleted_knowledge_references",
        lambda refs, tenant_id=None: reject_calls.append(list(refs)),
    )
    monkeypatch.setattr(
        skill_db_module,
        "create_or_update_skill_by_skill_info",
        lambda **kwargs: {"skill_instance_id": 1, "kwargs": kwargs},
    )
    ref = ref_service.KnowledgeResourceRef(provider="aidp", resource_id="kds-1")
    monkeypatch.setattr(
        skill_service_module.SkillService,
        "_skill_knowledge_references",
        staticmethod(lambda skill_info, tenant_id: [ref]),
    )

    result = skill_service_module.SkillService().create_or_update_skill_instance(
        SimpleNamespace(skill_id=5), "t1", "u1"
    )
    assert result["skill_instance_id"] == 1
    assert reject_calls == [[ref]]
    assert guard_calls == [[ref]]

    monkeypatch.setattr(
        skill_service_module.SkillService,
        "_skill_knowledge_references",
        staticmethod(lambda skill_info, tenant_id: []),
    )
    skill_service_module.SkillService().create_or_update_skill_instance(
        SimpleNamespace(skill_id=5), "t1", "u1"
    )
    assert len(reject_calls) == 1  # empty refs skip the deletion check
    assert guard_calls[-1] == []


# ---------------------------------------------------------------------------
# conversation scope update service
# ---------------------------------------------------------------------------


def _resolved_scope(
    *,
    warnings,
    aidp_kds_ids=("kds-1",),
    aidp_display_names=("A",),
):
    return SimpleNamespace(
        warnings=list(warnings),
        local_disabled=True,
        local_knowledge_ids=[],
        local_display_names=[],
        aidp_disabled=False,
        aidp_kds_ids=list(aidp_kds_ids),
        aidp_display_names=list(aidp_display_names),
    )


def _patch_update_deps(monkeypatch, conversation, resolved):
    monkeypatch.setattr(conversation_service, "get_conversation", lambda **kwargs: conversation)
    monkeypatch.setattr(
        conversation_service,
        "_resolve_knowledge_scope_for_update",
        lambda **kwargs: resolved,
    )
    monkeypatch.setattr(
        conversation_service,
        "update_conversation_knowledge_scope",
        lambda **kwargs: True,
    )


def test_conversation_scope_update_blocks_new_unavailable_ids(monkeypatch):
    conversation = {
        "conversation_id": 5,
        "agent_id": 7,
        "knowledge_scope": {"aidp": {"mode": "override", "kds_ids": ["kds-1"]}},
    }
    resolved = _resolved_scope(
        warnings=[
            {
                "code": "KNOWLEDGE_SCOPE_ITEM_UNAVAILABLE",
                "source": "aidp",
                "resource_ids": ["kds-2"],
            }
        ]
    )
    _patch_update_deps(monkeypatch, conversation, resolved)
    scope = {"schema_version": 1, "aidp": {"mode": "override", "kds_ids": ["kds-1", "kds-2"]}}
    with pytest.raises(ValidationError, match="unavailable or inaccessible"):
        conversation_service.update_conversation_knowledge_scope_service(
            5, scope, "u1", "t1"
        )


def test_conversation_scope_update_keeps_already_selected_unavailable_items(monkeypatch):
    conversation = {
        "conversation_id": 5,
        "agent_id": 7,
        "knowledge_scope": {"aidp": {"mode": "override", "kds_ids": ["kds-1"]}},
    }
    resolved = _resolved_scope(
        warnings=[
            {
                "code": "KNOWLEDGE_SCOPE_ITEM_UNAVAILABLE",
                "source": "aidp",
                "resource_ids": ["kds-1"],
            }
        ]
    )
    _patch_update_deps(monkeypatch, conversation, resolved)
    scope = {"schema_version": 1, "aidp": {"mode": "override", "kds_ids": ["kds-1"]}}
    result = conversation_service.update_conversation_knowledge_scope_service(
        5, scope, "u1", "t1"
    )
    assert result["warnings"] == resolved.warnings
    assert result["effective_preview"]["aidp"]["kds_ids"] == ["kds-1"]


def test_conversation_scope_update_without_agent_warns(monkeypatch):
    conversation = {"conversation_id": 5, "agent_id": None, "knowledge_scope": {}}
    _patch_update_deps(monkeypatch, conversation, _resolved_scope(warnings=[]))
    scope = {"schema_version": 1, "aidp": {"mode": "override", "kds_ids": ["kds-1"]}}
    result = conversation_service.update_conversation_knowledge_scope_service(
        5, scope, "u1", "t1"
    )
    assert result["warnings"] == [{"code": "KNOWLEDGE_SCOPE_AGENT_UNASSIGNED", "count": 1}]
    assert result["effective_preview"] is None


# ---------------------------------------------------------------------------
# knowledge scope resolvers
# ---------------------------------------------------------------------------


def test_capabilities_reports_configured_and_default_ids(monkeypatch):
    monkeypatch.setattr(scope_service, "resolve_root_version", lambda *a, **k: 1)
    monkeypatch.setattr(
        scope_service,
        "_walk_agent_tree",
        lambda *a, **k: [
            {
                "tools": [
                    {
                        "class_name": "KnowledgeBaseSearchTool",
                        "params": [{"name": "index_names", "default": ["idx-1"]}],
                    },
                    {
                        "class_name": "AidpSearchTool",
                        "params": [{"name": "kds_list", "default": ["kds-1"]}],
                    },
                ]
            }
        ],
    )
    monkeypatch.setattr(
        scope_service,
        "get_knowledge_info_by_tenant_id",
        lambda tenant_id: [{"index_name": "idx-1", "knowledge_id": 213}],
    )
    monkeypatch.setattr(scope_service, "get_knowledge_info_by_ids_and_tenant", lambda ids, tenant_id: [])
    monkeypatch.setattr(
        scope_service,
        "_filter_accessible_aidp_ids",
        lambda ids, user_id, tenant_id: list(ids),
    )
    monkeypatch.setattr(
        scope_service,
        "ElasticSearchService",
        SimpleNamespace(
            filter_accessible_indices=lambda names, user_id, tenant_id: list(names)
        ),
    )

    capabilities = scope_service.get_agent_knowledge_capabilities(
        7, "t1", None, user_id="u1"
    )
    aidp = capabilities["sources"]["aidp"]
    local = capabilities["sources"]["local"]
    assert local["configured_knowledge_ids"] == ["213"]
    assert local["default_knowledge_ids"] == ["213"]
    assert aidp["configured_knowledge_ids"] == ["kds-1"]
    assert aidp["default_knowledge_ids"] == ["kds-1"]


def test_resolve_local_override_reports_unavailable_ids(monkeypatch):
    monkeypatch.setattr(
        scope_service,
        "get_knowledge_info_by_ids_and_tenant",
        lambda ids, tenant_id: [
            {"knowledge_id": 1, "index_name": "idx-1", "embedding_model_id": 5}
        ],
    )
    monkeypatch.setattr(
        scope_service,
        "ElasticSearchService",
        SimpleNamespace(
            filter_accessible_indices=lambda names, user_id, tenant_id: ["idx-1"]
        ),
    )
    accessible, warnings = scope_service._resolve_local_override(
        ["1", "2", "not-a-number"], "u1", "t1"
    )
    assert [record["index_name"] for record in accessible] == ["idx-1"]
    assert warnings == [
        {
            "code": "KNOWLEDGE_SCOPE_ITEM_UNAVAILABLE",
            "source": "local",
            "count": 2,
            "resource_ids": ["2", "not-a-number"],
        }
    ]

    accessible, warnings = scope_service._resolve_local_override(["1"], "u1", "t1")
    assert warnings == []
