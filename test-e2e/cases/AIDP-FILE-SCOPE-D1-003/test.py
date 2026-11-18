# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Formal D1 coverage for the AIDP file-name scope filter."""

import json

import pytest

from nexent.core.ext_components.aidp import aidp_search_tool as tool_module
from nexent.core.ext_components.aidp import file_scope as file_scope_module
from nexent.core.ext_components.aidp.aidp_search_tool import AidpSearchTool

pytestmark = [pytest.mark.case_id("AIDP-FILE-SCOPE-D1-003"), pytest.mark.stage("D1")]


def _build_tool(file_scope=None, kds_list=None, search_method="vector_search"):
    params = {
        "server_url": "http://aidp.test",
        "api_key": "test-key",
        "tenant_id": "test-tenant",
        "kds_list": json.dumps(["kb-1"] if kds_list is None else kds_list),
        "search_method": search_method,
        "top_k": 7,
        "reranking_enable": False,
        "score_threshold": 0.25,
    }
    if file_scope is not None:
        params["file_scope"] = file_scope
    return AidpSearchTool(**params)


def _selected_scope(files):
    return {"mode": "selected", "files": files}


def test_selected_scope_sends_original_file_name_condition(monkeypatch):
    captured = {}

    def _records(client, url, api_key, payload):
        captured["payload"] = payload
        return [
            {
                "title": "a.txt",
                "text": "selected content",
                "metadata": {"original_file_name": "a.txt"},
            }
        ]

    monkeypatch.setattr(tool_module, "post_retrieval", _records)
    tool = _build_tool(
        _selected_scope(
            [
                {"kds_id": "kb-1", "file_uuid": "file-a", "file_name": "a.txt"},
                {"kds_id": "kb-1", "file_uuid": "file-b", "file_name": "b.txt"},
            ]
        )
    )

    result = tool.forward("question")

    condition = captured["payload"]["metadata_condition"]
    assert condition["logical_operator"] == "or"
    assert {item["value"] for item in condition["conditions"]} == {"a.txt", "b.txt"}
    assert {item["name"] for item in condition["conditions"]} == {
        "original_file_name"
    }
    assert "file_uuid_list" not in captured["payload"]
    assert result


def test_graph_retrieval_fails_closed_for_file_scope(monkeypatch):
    calls = []

    def _unexpected(*args, **kwargs):
        calls.append(kwargs)
        raise AssertionError("FusionSearch must not be called")

    monkeypatch.setattr(tool_module, "post_retrieval", _unexpected)
    tool = _build_tool(
        _selected_scope(
            [{"kds_id": "kb-1", "file_uuid": "file-a", "file_name": "a.txt"}]
        ),
        search_method="vector_search|graph_search",
    )

    result = tool.forward("question")

    assert result == file_scope_module.FILE_SCOPE_GRAPH_UNSUPPORTED_MESSAGE
    assert calls == []


def test_selected_file_without_name_fails_closed(monkeypatch):
    calls = []

    def _unexpected(*args, **kwargs):
        calls.append(kwargs)
        raise AssertionError("FusionSearch must not be called")

    monkeypatch.setattr(tool_module, "post_retrieval", _unexpected)
    tool = _build_tool(
        _selected_scope([{"kds_id": "kb-1", "file_uuid": "file-a"}])
    )

    result = tool.forward("question")

    assert result == file_scope_module.FILE_SCOPE_UNAVAILABLE_MESSAGE
    assert calls == []


def test_all_mode_preserves_retrieval_configuration(monkeypatch):
    captured = {}

    def _empty_response(client, url, api_key, payload):
        captured["payload"] = payload
        return []

    monkeypatch.setattr(tool_module, "post_retrieval", _empty_response)
    tool = _build_tool({"mode": "all", "files": []})

    tool.forward("question")

    payload = captured["payload"]
    assert payload["topk"] == 7
    assert payload["search_method"] == "vector_search"
    assert payload["score_threshold"] == 0.25
    assert "reranking_mode" not in payload
    assert payload["kds_list"] == ["kb-1"]
    assert "metadata_condition" not in payload
    assert "file_scope" not in payload


def test_out_of_scope_record_fails_closed(monkeypatch):
    def _records(client, url, api_key, payload):
        return [
            {
                "title": "z.txt",
                "text": "outside the selection",
                "metadata": {"original_file_name": "z.txt"},
            }
        ]

    monkeypatch.setattr(tool_module, "post_retrieval", _records)
    tool = _build_tool(
        _selected_scope(
            [{"kds_id": "kb-1", "file_uuid": "file-a", "file_name": "a.txt"}]
        )
    )

    result = tool.forward("question")

    assert result == file_scope_module.FILE_SCOPE_VIOLATION_MESSAGE


def test_malformed_file_scope_is_rejected():
    with pytest.raises(ValueError):
        _build_tool('{"mode": "selected", "files": "not-a-list"}')
