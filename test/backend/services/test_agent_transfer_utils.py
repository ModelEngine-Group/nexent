# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Regression coverage for platform AIDP agent transfers."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

from consts.exceptions import (
    AgentToolImportError,
)
from management.services.agent.policy import (
    portable_tool_params,
    prepare_import_retrieval_params,
    validate_import_tool_params,
)


def test_aidp_runtime_fields_are_removed_without_mutating_snapshot():
    params = {"api_key": "secret", "server_url": "private", "tenant_id": "old",
              "kds_list": ["kb"], "top_k": 5}
    result = validate_import_tool_params(
        "AidpSearchTool", "local", params,
        {"params": [{"name": "kds_list"}, {"name": "top_k"}]},
    )
    assert result == {"kds_list": ["kb"], "top_k": 5}
    result["kds_list"].append("another")
    assert params["kds_list"] == ["kb"]
    assert params["api_key"] == "secret"


@pytest.mark.parametrize("class_name", ["IndependentAidpSearchTool", "OtherTool"])
def test_other_tools_keep_their_own_credentials(class_name):
    assert portable_tool_params(class_name, {"api_key": "own"}) == {"api_key": "own"}


def test_unknown_business_parameter_is_not_silently_dropped():
    with pytest.raises(AgentToolImportError, match="unexpected"):
        validate_import_tool_params("AidpSearchTool", "local", {"unexpected": 1}, {"params": []})


def test_missing_tool_reports_domain_error():
    with pytest.raises(AgentToolImportError, match="Cannot find tool"):
        validate_import_tool_params("AidpSearchTool", "local", {}, None)


def test_external_import_prepares_policy_once_and_snapshot_import_does_not(monkeypatch):
    config = {"top_k": 7, "search_method": "hybrid_search"}
    tool = SimpleNamespace(class_name="AidpSearchTool", params=config)
    uploaded = SimpleNamespace(agent_info={"1": SimpleNamespace(tools=[tool])})
    prepare_import_retrieval_params(uploaded)
    assert tool.params["search_method"] == "vector_search|full_text_search|graph_search"
    import management.services.agent.policy as policy
    check = MagicMock()
    monkeypatch.setattr(policy, "prepare_config", check)
    catalog = {"params": [{"name": name} for name in config]}
    assert validate_import_tool_params("AidpSearchTool", "local", config, catalog) == config
    check.assert_not_called()


@pytest.mark.parametrize("class_name", ["AidpSearchTool", "IndependentAidpSearchTool"])
def test_external_import_rejects_invalid_raw_policy(class_name):
    tool = SimpleNamespace(class_name=class_name, params={"reranking_enable": False, "graph_reranking_enable": True})
    with pytest.raises(AgentToolImportError, match="graph_reranking_enable"):
        prepare_import_retrieval_params(SimpleNamespace(agent_info={"1": SimpleNamespace(tools=[tool])}))


def test_external_import_accepts_omitted_tool_params():
    tool = SimpleNamespace(class_name="AidpSearchTool", params=None)
    prepare_import_retrieval_params(SimpleNamespace(agent_info={"1": SimpleNamespace(tools=[tool])}))
    assert tool.params == {}
