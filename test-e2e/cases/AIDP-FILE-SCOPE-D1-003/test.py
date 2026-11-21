# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Formal D1 coverage for the AIDP metadata-filter request payload."""

import json

import pytest
from nexent.core.ext_components.aidp import aidp_search_tool as tool_module
from nexent.core.ext_components.aidp import metadata_filter as filter_module
from nexent.core.ext_components.aidp.aidp_search_tool import AidpSearchTool

pytestmark = [pytest.mark.case_id("AIDP-FILE-SCOPE-D1-003"), pytest.mark.stage("D1")]


def _build_tool(metadata_filter=None, kds_list=None, search_method="vector_search"):
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
    if metadata_filter is not None:
        params["metadata_filter"] = metadata_filter
    return AidpSearchTool(**params)


def _enabled_filter(operator="contains", value="合同"):
    return {
        "enabled": True,
        "file_name": {"operator": operator, "value": value},
    }


@pytest.mark.parametrize(
    "operator,wire_operator",
    [
        ("contains", "contains"),
        ("is", "is"),
        ("starts_with", "start with"),
        ("ends_with", "end with"),
    ],
)
def test_filter_builds_single_original_file_name_condition(
    monkeypatch, operator, wire_operator
):
    captured = {}

    def _records(client, url, api_key, payload):
        captured["payload"] = payload
        return []

    monkeypatch.setattr(tool_module, "post_retrieval", _records)
    tool = _build_tool(_enabled_filter(operator))

    tool.forward("question")

    condition = captured["payload"]["metadata_condition"]
    assert condition["logical_operator"] == "and"
    assert condition["conditions"] == [
        {
            "name": "original_file_name",
            "comparison_operator": wire_operator,
            "value": "合同",
        }
    ]
    assert "file_scope" not in captured["payload"]


def test_graph_retrieval_fails_closed_for_metadata_filter(monkeypatch):
    calls = []

    def _unexpected(*args, **kwargs):
        calls.append(kwargs)
        raise AssertionError("FusionSearch must not be called")

    monkeypatch.setattr(tool_module, "post_retrieval", _unexpected)
    tool = _build_tool(
        _enabled_filter(),
        search_method="vector_search|graph_search",
    )

    result = tool.forward("question")

    assert result == filter_module.FILTER_GRAPH_UNSUPPORTED_MESSAGE
    assert calls == []


def test_disabled_filter_preserves_retrieval_configuration(monkeypatch):
    captured = {}

    def _empty_response(client, url, api_key, payload):
        captured["payload"] = payload
        return []

    monkeypatch.setattr(tool_module, "post_retrieval", _empty_response)
    tool = _build_tool({"enabled": False})

    tool.forward("question")

    payload = captured["payload"]
    assert payload["topk"] == 7
    assert payload["search_method"] == "vector_search"
    assert payload["score_threshold"] == 0.25
    assert "reranking_mode" not in payload
    assert payload["kds_list"] == ["kb-1"]
    assert "metadata_condition" not in payload
    assert "file_scope" not in payload


def test_unsupported_operator_fails_closed_without_request(monkeypatch):
    calls = []

    def _unexpected(*args, **kwargs):
        calls.append(kwargs)
        raise AssertionError("FusionSearch must not be called")

    monkeypatch.setattr(tool_module, "post_retrieval", _unexpected)
    tool = _build_tool(_enabled_filter(operator="equals"))

    result = tool.forward("question")

    assert result == filter_module.FILTER_UNAVAILABLE_MESSAGE
    assert calls == []


def test_malformed_filter_is_rejected():
    with pytest.raises(ValueError):
        _build_tool({"enabled": True, "file_name": "not-an-object"})
