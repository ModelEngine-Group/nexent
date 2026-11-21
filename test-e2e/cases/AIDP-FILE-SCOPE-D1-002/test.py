# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Formal D1 coverage for resolving AIDP metadata filters into tool parameters."""

import json
from types import SimpleNamespace

import pytest
from contracts.knowledge import ConversationKnowledgeScopeRequest
from contracts.tool import ToolParamsRequest
from management.services.knowledge_base import scope as scope_module

pytestmark = [pytest.mark.case_id("AIDP-FILE-SCOPE-D1-002"), pytest.mark.stage("D1")]


def _tool(kds_ids):
    return {
        "class_name": "AidpSearchTool",
        "name": "aidp_search",
        "params": [{"name": "kds_list", "default": json.dumps(kds_ids)}],
    }


def _tree(*ranges):
    return [
        {"runtime_ref": name, "tools": [_tool(kds_ids)]}
        for name, kds_ids in ranges
    ]


def _scope(
    *,
    enabled=True,
    operator="contains",
    value="合同",
    aidp_mode="override",
    kds_ids=None,
):
    payload = {
        "schema_version": 3 if enabled else 1,
        "local": {"mode": "inherit", "knowledge_ids": []},
        "aidp": {
            "mode": aidp_mode,
            "kds_ids": ["kb-1"] if kds_ids is None and aidp_mode == "override" else (kds_ids or []),
        },
    }
    if enabled:
        payload["aidp"]["metadata_filter"] = {
            "enabled": True,
            "file_name": {"operator": operator, "value": value},
        }
    return ConversationKnowledgeScopeRequest.model_validate(payload)


def _resolve(monkeypatch, scope, tree, accessible, request_tool_params=None):
    monkeypatch.setattr(
        scope_module,
        "_resolve_aidp_access_snapshot",
        lambda *args, **kwargs: SimpleNamespace(
            accessible_id_set=set(accessible),
            name_to_id={f"KB {kds_id}": kds_id for kds_id in accessible},
        ),
    )
    return scope_module.resolve_knowledge_scope(
        scope=scope,
        agent_id=1,
        tenant_id="tenant",
        user_id="user",
        version_no=1,
        is_debug=False,
        request_tool_params=request_tool_params,
        runtime_agent_tree=tree,
    )


def test_filter_is_projected_to_every_aidp_tool(monkeypatch):
    resolved = _resolve(
        monkeypatch,
        _scope(operator="starts_with", value="年度报告", kds_ids=["kb-1", "kb-2"]),
        _tree(("root", ["kb-1", "kb-2"]), ("child", ["kb-1"])),
        {"kb-1", "kb-2"},
    )

    root = resolved.tool_params.agents["root"].tools["aidp_search"]
    child = resolved.tool_params.agents["child"].tools["aidp_search"]
    assert root["kds_list"] == ["kb-1", "kb-2"]
    assert child["kds_list"] == ["kb-1", "kb-2"]
    expected = {
        "enabled": True,
        "file_name": {"operator": "starts_with", "value": "年度报告"},
    }
    assert root["metadata_filter"] == expected
    assert child["metadata_filter"] == expected
    assert resolved.aidp_metadata_filter == expected
    assert "file_scope" not in root


def test_disabled_filter_adds_no_parameter(monkeypatch):
    resolved = _resolve(
        monkeypatch,
        _scope(enabled=False),
        _tree(("root", ["kb-1"])),
        {"kb-1"},
    )

    params = resolved.tool_params.agents["root"].tools["aidp_search"]
    assert "metadata_filter" not in params
    assert resolved.aidp_metadata_filter == {"enabled": False}


def test_filter_survives_inherit_mode_and_bounded_request_params(monkeypatch):
    resolved = _resolve(
        monkeypatch,
        _scope(aidp_mode="inherit", kds_ids=[]),
        _tree(("root", ["kb-1"]), ("child", ["kb-2"])),
        {"kb-1", "kb-2"},
    )
    root = resolved.tool_params.agents["root"].tools["aidp_search"]
    child = resolved.tool_params.agents["child"].tools["aidp_search"]
    assert root["kds_list"] == ["kb-1"]
    assert child["kds_list"] == ["kb-2"]
    assert root["metadata_filter"]["file_name"]["value"] == "合同"
    assert child["metadata_filter"]["file_name"]["value"] == "合同"

    request_params = ToolParamsRequest.model_validate(
        {
            "agents": {
                "root": {
                    "tools": {
                        "aidp_search": {
                            "kds_list": ["kb-1", "kb-2", "kb-3"],
                            "metadata_filter": {
                                "enabled": True,
                                "file_name": {"operator": "is", "value": "other"},
                            },
                        }
                    }
                }
            }
        }
    )
    bounded = _resolve(
        monkeypatch,
        _scope(kds_ids=["kb-1"]),
        _tree(("root", ["kb-1"])),
        {"kb-1"},
        request_tool_params=request_params,
    )
    params = bounded.tool_params.agents["root"].tools["aidp_search"]
    assert params["kds_list"] == ["kb-1"]
    assert params["metadata_filter"]["file_name"] == {
        "operator": "contains",
        "value": "合同",
    }
