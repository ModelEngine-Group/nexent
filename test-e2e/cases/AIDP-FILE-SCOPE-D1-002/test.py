# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Formal D1 coverage for resolving AIDP file scopes into tool parameters."""

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


def _scope(files, *, aidp_mode="override", kds_ids=None):
    return ConversationKnowledgeScopeRequest.model_validate(
        {
            "schema_version": 2,
            "local": {"mode": "inherit", "knowledge_ids": []},
            "aidp": {
                "mode": aidp_mode,
                "kds_ids": kds_ids if kds_ids is not None else sorted({item["kds_id"] for item in files}),
                "file_scope": {"mode": "selected", "files": files},
            },
        }
    )


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


def _file_pairs(file_scope):
    return [(item["kds_id"], item["file_uuid"]) for item in file_scope["files"]]


def test_selected_files_are_projected_per_tool(monkeypatch):
    resolved = _resolve(
        monkeypatch,
        _scope(
            [
                {"kds_id": "kb-1", "file_uuid": "file-a", "file_name": "a.txt"},
                {"kds_id": "kb-2", "file_uuid": "file-b", "file_name": "b.txt"},
            ]
        ),
        _tree(("root", ["kb-1", "kb-2"]), ("child", ["kb-1"])),
        {"kb-1", "kb-2"},
    )

    root = resolved.tool_params.agents["root"].tools["aidp_search"]
    child = resolved.tool_params.agents["child"].tools["aidp_search"]
    assert root["kds_list"] == ["kb-1", "kb-2"]
    assert child["kds_list"] == ["kb-1", "kb-2"]
    assert _file_pairs(root["file_scope"]) == [("kb-1", "file-a"), ("kb-2", "file-b")]
    assert _file_pairs(child["file_scope"]) == [("kb-1", "file-a"), ("kb-2", "file-b")]
    assert resolved.aidp_file_scope["mode"] == "selected"
    assert len(resolved.aidp_file_scope["files"]) == 2


def test_out_of_range_and_empty_selected_fail_closed(monkeypatch):
    tree = _tree(("root", ["kb-1", "kb-3"]))
    mixed = _resolve(
        monkeypatch,
        _scope(
            [
                {"kds_id": "kb-1", "file_uuid": "file-a", "file_name": "a.txt"},
                {"kds_id": "kb-3", "file_uuid": "file-c", "file_name": "c.txt"},
            ],
            kds_ids=["kb-1", "kb-3"],
        ),
        tree,
        {"kb-1"},
    )

    mixed_scope = mixed.tool_params.agents["root"].tools["aidp_search"]["file_scope"]
    assert _file_pairs(mixed_scope) == [("kb-1", "file-a")]
    assert any(
        warning["code"] == "KNOWLEDGE_SCOPE_FILE_UNAVAILABLE" and warning["count"] == 1
        for warning in mixed.warnings
    )

    empty = _resolve(
        monkeypatch,
        _scope(
            [{"kds_id": "kb-3", "file_uuid": "file-c", "file_name": "c.txt"}],
            kds_ids=["kb-3"],
        ),
        tree,
        {"kb-1"},
    )
    empty_scope = empty.tool_params.agents["root"].tools["aidp_search"]["file_scope"]
    assert empty_scope == {"mode": "selected", "files": []}
    assert empty.aidp_file_scope["mode"] == "selected"
    assert empty.aidp_file_scope["files"] == []


def test_selected_file_scope_applies_to_every_tool(monkeypatch):
    resolved = _resolve(
        monkeypatch,
        _scope(
            [{"kds_id": "kb-1", "file_uuid": "file-a", "file_name": "a.txt"}],
            aidp_mode="inherit",
            kds_ids=[],
        ),
        _tree(("root", ["kb-1"]), ("child", ["kb-2"])),
        {"kb-1", "kb-2"},
    )
    inherit_params = resolved.tool_params.agents["root"].tools["aidp_search"]
    child_params = resolved.tool_params.agents["child"].tools["aidp_search"]
    assert inherit_params["kds_list"] == ["kb-1"]
    assert child_params["kds_list"] == ["kb-1"]
    assert _file_pairs(inherit_params["file_scope"]) == [("kb-1", "file-a")]
    assert _file_pairs(child_params["file_scope"]) == [("kb-1", "file-a")]

    request_params = ToolParamsRequest.model_validate(
        {
            "agents": {
                "root": {
                    "tools": {
                        "aidp_search": {
                            "kds_list": ["kb-1", "kb-2", "kb-3"],
                            "file_scope": {"mode": "all", "files": []},
                        }
                    }
                }
            }
        }
    )
    bounded = _resolve(
        monkeypatch,
        _scope(
            [{"kds_id": "kb-1", "file_uuid": "file-a", "file_name": "a.txt"}],
            kds_ids=["kb-1"],
        ),
        _tree(("root", ["kb-1"])),
        {"kb-1"},
        request_tool_params=request_params,
    )
    params = bounded.tool_params.agents["root"].tools["aidp_search"]
    assert params["kds_list"] == ["kb-1"]
    assert _file_pairs(params["file_scope"]) == [("kb-1", "file-a")]
